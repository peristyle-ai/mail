"""
HTTP client for the local Qwen3-Embedding-4B server.

Wraps `POST /v1/embeddings` on the text-embeddings-router running on
127.0.0.1:8080 (root PID 5086 on localhost). Adds:

    * dimension override    — we request 1024-dim Matryoshka vectors so the
                              pgvector halfvec column doesn't blow past the
                              3000-dim HNSW ceiling (MEMORY.md 2026-08-16)
    * batching              — up to MAX_BATCH texts per request; the GPU
                              server caps at max-client-batch-size=32 with
                              max-batch-tokens=8192
    * retry + backoff       — exponential backoff on 5xx / connection errors
    * timeout               — 30s per request; if a batch can't make it
                              through, the worker will retry the job

The class is intentionally sync — the worker is itself a single-threaded
daemon, so an async client would just add complexity without parallelism.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

import requests

logger = logging.getLogger(__name__)


# Hard cap that matches the GPU server's `--max-client-batch-size=32`. If
# we send more, the server rejects with a 400.
MAX_BATCH_SIZE = 32

# Per-request HTTP timeout. The first call after idle is the slowest
# (model load on first inference) — anything in flight past 30s is broken.
REQUEST_TIMEOUT_SECONDS = 30.0

# Retry policy for transient failures (5xx, connection refused, timeouts).
MAX_RETRIES = 4
RETRY_BACKOFF_BASE_SECONDS = 0.5
RETRY_BACKOFF_CAP_SECONDS = 8.0


class EmbeddingError(Exception):
    """Raised when the embedding server is unreachable or returns a non-2xx
    that survived all retries. The worker treats this as a job-level failure
    and reschedules with backoff."""


@dataclass
class EmbeddingConfig:
    base_url: str
    model: str
    dimensions: int

    @classmethod
    def from_env_and_config(cls) -> 'EmbeddingConfig':
        """Read EMBEDDING_GPU_URL / EMBEDDING_MODEL / EMBEDDING_DIMENSIONS env
        vars, falling back to config.yaml (`embedding.*`) and finally to
        the local defaults."""
        from config import get_config
        cfg = get_config()
        base_url = (
            os.environ.get('EMBEDDING_GPU_URL')
            or f"http://{os.environ.get('EMBEDDING_GPU_HOST', '127.0.0.1')}:"
               f"{os.environ.get('EMBEDDING_GPU_PORT', '8080')}"
        )
        model = (
            os.environ.get('EMBEDDING_MODEL')
            or os.environ.get('MEMORY_SEARCH_MODEL')
            or 'Qwen/Qwen3-Embedding-4B'
        )
        dims_str = os.environ.get('EMBEDDING_DIMENSIONS')
        if dims_str:
            dimensions = int(dims_str)
        else:
            dimensions = 1024
        return cls(base_url=base_url, model=model, dimensions=dimensions)


class EmbeddingService:
    """Thin wrapper over the local embedding HTTP server."""

    def __init__(self, config: Optional[EmbeddingConfig] = None) -> None:
        self.config = config or EmbeddingConfig.from_env_and_config()
        # Persistent session reuses the TCP connection.
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    # --- public --------------------------------------------------------------

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a batch of strings.

        Returns one vector per input, in input order. The caller is
        responsible for keeping the batch within the server's limits
        (we auto-chunk into MAX_BATCH_SIZE-sized requests).

        Raises EmbeddingError after MAX_RETRIES failed attempts.
        """
        if not texts:
            return []
        # Drop empty strings (the server rejects them with a 400). Map back
        # by index so the caller's ordering is preserved.
        valid: List[str] = []
        valid_index: List[int] = []
        for i, t in enumerate(texts):
            t = (t or '').strip()
            if t:
                valid.append(t)
                valid_index.append(i)
        if not valid:
            return [[] for _ in texts]

        results: List[Optional[List[float]]] = [None] * len(texts)
        for start in range(0, len(valid), MAX_BATCH_SIZE):
            batch = valid[start:start + MAX_BATCH_SIZE]
            vectors = self._embed_with_retry(batch)
            for offset, vec in enumerate(vectors):
                results[valid_index[start + offset]] = vec

        # Pad any Nones (shouldn't happen — we filtered empties above).
        return [r if r is not None else [] for r in results]

    def embed_one(self, text: str) -> List[float]:
        """Convenience wrapper for single-string embedding.

        Subject embedding uses this; it's the common case during live
        inbound (each new email = one subject).
        """
        if not text or not text.strip():
            raise EmbeddingError('embed_one called with empty text')
        out = self.embed_batch([text])
        return out[0]

    def healthcheck(self) -> bool:
        """Quick reachability probe. Doesn't actually embed anything."""
        try:
            r = self._session.get(
                f"{self.config.base_url}/health",
                timeout=2.0,
            )
            return r.ok
        except requests.RequestException:
            return False

    # --- internals -----------------------------------------------------------

    def _embed_with_retry(self, batch: Sequence[str]) -> List[List[float]]:
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._embed_once(batch)
            except requests.HTTPError as e:
                # 4xx (other than 429) is a code bug, not a transient error.
                status = getattr(getattr(e, 'response', None), 'status_code', None)
                if status and 400 <= status < 500 and status != 429:
                    raise EmbeddingError(
                        f"Embedding server rejected batch: HTTP {status} "
                        f"({e.response.text[:200] if e.response is not None else ''})"
                    ) from e
                last_err = e
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
            if attempt < MAX_RETRIES:
                backoff = min(
                    RETRY_BACKOFF_CAP_SECONDS,
                    RETRY_BACKOFF_BASE_SECONDS * (2 ** attempt),
                )
                logger.warning(
                    "embedding transient failure (attempt %d/%d): %s; "
                    "sleeping %.2fs before retry",
                    attempt + 1, MAX_RETRIES + 1, last_err, backoff,
                )
                time.sleep(backoff)
        raise EmbeddingError(
            f"Embedding server unreachable after {MAX_RETRIES + 1} attempts: "
            f"{last_err}"
        )

    def _embed_once(self, batch: Sequence[str]) -> List[List[float]]:
        payload = {
            'input': list(batch),
            'model': self.config.model,
            'dimensions': self.config.dimensions,
        }
        r = self._session.post(
            f"{self.config.base_url}/v1/embeddings",
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if not r.ok:
            # Raise so _embed_with_retry can decide whether to retry.
            raise requests.HTTPError(
                f"HTTP {r.status_code} from embedding server",
                response=r,
            )
        try:
            data = r.json()
        except ValueError as e:
            raise EmbeddingError(f"Non-JSON response from embedding server: {e}") from e
        rows = data.get('data') or []
        if len(rows) != len(batch):
            raise EmbeddingError(
                f"Embedding server returned {len(rows)} vectors for "
                f"{len(batch)} inputs"
            )
        # Sort by `index` defensively in case the server returns them
        # out of order (it doesn't today, but the OpenAI spec allows it).
        rows.sort(key=lambda row: row.get('index', 0))
        return [row['embedding'] for row in rows]
