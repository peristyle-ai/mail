"""
Email utilities: header parsing, thread-ID computation.

This module is the canonical home for RFC 2822 threading helpers used at
both insert-time (live capture in app/routes/, smtp_server/) and one-shot
backfill time (scripts/backfill_threads.py). See
coding_agent/plan_threading.md for the full design.

Pure helpers (no DB):
    * normalize_subject
    * extract_threading_headers
    * extract_from_headers_blob

DB-backed helpers (need a cursor passed in):
    * compute_thread_id
"""
from __future__ import annotations

import re
import uuid
from email import message_from_string
from typing import Optional


# =============================================================================
# Subject normalization
# =============================================================================

_RE_PREFIX = re.compile(r"^\s*(re|fwd|fw)\s*:\s*", re.IGNORECASE)


def normalize_subject(subject: Optional[str]) -> str:
    """Strip leading Re:/Fwd:/Fw: prefixes (case-insensitive, repeated) and
    lower-case the result. Returns '' for empty/None input.

    >>> normalize_subject("Re: hello")
    'hello'
    >>> normalize_subject("Re: RE: Fwd: re: hello")
    'hello'
    >>> normalize_subject(None)
    ''
    """
    if not subject:
        return ""
    s = subject.strip()
    while True:
        new = _RE_PREFIX.sub("", s, count=1)
        if new == s:
            break
        s = new
    return s.lower()


# =============================================================================
# Threading header extraction
# =============================================================================

def _strip_brackets(msg_id: str) -> str:
    """Strip surrounding angle brackets and whitespace. Tolerate missing
    brackets (some clients send bare Message-IDs)."""
    s = msg_id.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    return s


def extract_threading_headers(raw_text: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse Message-ID / In-Reply-To / References from a raw RFC 2822
    message.

    Returns (message_id, in_reply_to, references) - all without angle
    brackets. Any missing header is None.
    """
    if not raw_text:
        return None, None, None
    try:
        msg = message_from_string(raw_text)
    except Exception:
        return None, None, None

    mid = _strip_brackets(msg.get("Message-ID", "") or "")
    irt = _strip_brackets(msg.get("In-Reply-To", "") or "")

    refs_raw = (msg.get("References", "") or "").strip()
    if refs_raw:
        # References is a space-separated list of Message-IDs, each
        # optionally surrounded by angle brackets.
        parts = [_strip_brackets(p) for p in refs_raw.split()]
        refs = " ".join(p for p in parts if p)
    else:
        refs = ""

    return (mid or None, irt or None, refs or None)


def extract_from_headers_blob(headers_blob: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fallback parser for the `headers` column (newline-separated
    'K: V' pairs). Covers rows where raw_email wasn't stored."""
    if not headers_blob:
        return None, None, None
    mid = irt = refs = None
    for line in headers_blob.splitlines():
        if line.startswith((" ", "\t")):
            continue  # folded continuation
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name_lc = name.strip().lower()
        value = value.strip()
        if name_lc == "message-id" and not mid:
            mid = _strip_brackets(value)
        elif name_lc == "in-reply-to" and not irt:
            irt = _strip_brackets(value)
        elif name_lc == "references" and not refs:
            parts = [_strip_brackets(p) for p in value.split()]
            refs = " ".join(p for p in parts if p)
    return (mid or None, irt or None, refs or None)


# =============================================================================
# Thread-ID computation (requires a DB cursor)
# =============================================================================

MAX_CHAIN_DEPTH = 50  # guard against References / In-Reply-To cycles


def _resolve_by_references(cursor, refs: str, candidate_root_id: Optional[int]) -> tuple[Optional[str], str]:
    """Walk the References chain. If any Message-ID in the chain already
    exists in the DB, return its thread_id (minting one if the row's
    thread_id is still NULL). Otherwise return (None, 'no_chain_match')."""
    if not refs:
        return None, "no_refs"
    for mid in refs.split():
        cursor.execute(
            "SELECT id, thread_id FROM emails WHERE message_id = %s LIMIT 1",
            (mid,),
        )
        row = cursor.fetchone()
        if row and row["id"] != candidate_root_id:
            if row["thread_id"]:
                return row["thread_id"], "references"
            new_tid = str(uuid.uuid4())
            cursor.execute(
                "UPDATE emails SET thread_id = %s WHERE id = %s AND thread_id IS NULL",
                (new_tid, row["id"]),
            )
            return new_tid, "references"
    return None, "no_chain_match"


def _resolve_by_in_reply_to(cursor, irt: str, candidate_root_id: Optional[int]) -> tuple[Optional[str], str]:
    """Walk `message_id = in_reply_to` recursively to find the root."""
    if not irt:
        return None, "no_irt"
    current_mid = irt
    visited = set()
    for _ in range(MAX_CHAIN_DEPTH):
        if current_mid in visited:
            return None, "cycle"
        visited.add(current_mid)
        cursor.execute(
            """
            SELECT e.id, e.thread_id, e.in_reply_to
              FROM emails e
             WHERE e.message_id = %s
             ORDER BY e.id ASC
             LIMIT 1
            """,
            (current_mid,),
        )
        row = cursor.fetchone()
        if not row:
            return None, "irt_not_found"
        if row["id"] == candidate_root_id:
            return None, "self_parent"
        if row["thread_id"]:
            return row["thread_id"], "in_reply_to"
        if not row["in_reply_to"]:
            new_tid = str(uuid.uuid4())
            cursor.execute(
                "UPDATE emails SET thread_id = %s WHERE id = %s AND thread_id IS NULL",
                (new_tid, row["id"]),
            )
            return new_tid, "in_reply_to"
        current_mid = row["in_reply_to"]
    return None, "depth_exceeded"


def _participants_key(cursor, email_id: int) -> Optional[frozenset]:
    """Return a stable set of (sender_id, recipient_user_ids) for an email.
    None if sender is missing (shouldn't happen, but be defensive)."""
    cursor.execute("SELECT sender_id FROM emails WHERE id = %s", (email_id,))
    row = cursor.fetchone()
    if not row or row["sender_id"] is None:
        return None
    sender_id = row["sender_id"]
    cursor.execute(
        "SELECT user_id FROM email_recipients WHERE email_id = %s",
        (email_id,),
    )
    recipients = {r["user_id"] for r in cursor.fetchall()}
    return frozenset({sender_id, *recipients})


def compute_thread_id(
    cursor,
    message_id: Optional[str],
    in_reply_to: Optional[str],
    references_chain: Optional[str],
    candidate_root_id: Optional[int] = None,
    subject_normalized: Optional[str] = None,
) -> tuple[str, str]:
    """Decide what thread_id this email belongs to.

    Priority (per coding_agent/plan_threading.md D6):
        1. References chain      -> adopt an existing row's thread_id
        2. In-Reply-To walk      -> adopt the chain root's thread_id
        3. Subject fallback      -> uuid5 of (subject, sorted participants)
        4. Lone message          -> fresh uuid4 (so no row is ever orphaned)

    Returns (thread_id, strategy) where strategy is one of:
        'references' / 'in_reply_to' / 'subject_fallback' / 'lone_message'
    """
    if references_chain:
        tid, strategy = _resolve_by_references(cursor, references_chain, candidate_root_id)
        if tid:
            return tid, strategy

    if in_reply_to:
        tid, strategy = _resolve_by_in_reply_to(cursor, in_reply_to, candidate_root_id)
        if tid:
            return tid, strategy

    if subject_normalized:
        pk = _participants_key(cursor, candidate_root_id) if candidate_root_id else None
        if pk:
            tid = uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"py_pg_email|subject|{subject_normalized}|{','.join(str(x) for x in sorted(pk))}",
            )
            return str(tid), "subject_fallback"

    return str(uuid.uuid4()), "lone_message"