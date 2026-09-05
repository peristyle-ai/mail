#!/usr/bin/env python3
"""
Entrypoint for the embedding worker systemd --user service.

The systemd unit (systemd/user/mail-server-embeddings.service) ExecStarts
this script. It just configures logging + hands control to
`app.services.embedding_worker.main()`.

Also usable in ops mode:

    EMBEDDING_WORKER_MODE=once python scripts/run_embedding_worker.py
        # process everything pending, exit (for catch-up + tests)
"""

from __future__ import annotations

import os
import sys

# Make `app` importable when the script is run directly (systemd unit does
# `WorkingDirectory=__PROJECT_ROOT__`, so this is belt-and-suspenders).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def main() -> int:
    from app.services.embedding_worker import main as worker_main
    return worker_main()


if __name__ == '__main__':
    sys.exit(main())
