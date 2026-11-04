#!/usr/bin/env python3
"""
Backfill `email_recipients` for mail that was stored BEFORE the app began
writing that table.

WHY THIS EXISTS
---------------
The /api/threads family matches incoming mail with

    (e.sender_id = %s OR er.user_id = %s)

where `er` is `email_recipients`. The table is written by the inbound webhook
and by the SMTP receiver, so mail that arrives NOW gets its recipient rows.
But mail that was already in the database never did: `email_recipients` was
introduced by the migrations, and no backfill was ever written for the rows
that predate it.

The consequence is that an inbox full of older mail renders as EMPTY in the
threaded view, while the legacy per-email view still shows it (that one still
reads `emails.recipient_id`). On 2026-11-05 the peristyle account had 63
emails in its Inbox and the threaded view showed none of them.

This script writes the missing rows using the SAME logic the app uses:

  * To and Cc are parsed from the stored raw message with the same
    `email.parser` + `email.utils.getaddresses` calls the inbound path uses;
  * each address is resolved to a local user with the same rule the inbound
    path uses (the user must exist AND be local);
  * one row per address, `recipient_type` in ('to', 'cc') - the same
    constraint the table carries.

WHERE THE RECIPIENT COMES FROM
------------------------------
  * the To/Cc headers of the stored message, when it can be parsed - this is
    what the app does, and it finds EVERY recipient;
  * otherwise the email's `recipient_id`, the column the older code used,
    which still holds the primary recipient.

IT IS IDEMPOTENT
----------------
Only emails with NO rows in `email_recipients` are touched, so running it
again is a no-op, and mail that arrives while it runs is not doubled up
(it arrives with its own rows, and the script's own query re-checks).

    python scripts/backfill_email_recipients.py --dry-run
    python scripts/backfill_email_recipients.py --limit 100
    python scripts/backfill_email_recipients.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse  # noqa: E402
from email import policy  # noqa: E402
from email.parser import Parser  # noqa: E402
from email.utils import getaddresses  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    load_dotenv(os.path.join(ROOT, '.env'))
except OSError:
    # The .env may be unreadable when this runs as a role that is not the
    # install's user. An explicit DATABASE_URL in the environment still
    # works; load_dotenv does not override what is already set.
    pass

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402


def parse_recipients(raw_email):
    """Return (to_addresses, cc_addresses) from a stored raw message.

    The same parsing the inbound path does, so the rows this script writes
    are the rows the app would have written.
    """
    if not raw_email:
        return [], []
    try:
        msg = Parser(policy=policy.default).parsestr(raw_email)
    except Exception:
        return [], []

    def addresses(header):
        value = msg.get(header, '')
        if not value:
            return []
        try:
            return [addr[1] for addr in getaddresses([value]) if addr[1]]
        except Exception:
            return []

    return addresses('To'), addresses('Cc')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='report what would be inserted, change nothing')
    ap.add_argument('--limit', type=int, default=0,
                    help='stop after N emails (0 = no limit)')
    args = ap.parse_args()

    url = os.environ.get('DATABASE_URL')
    if not url:
        print('DATABASE_URL is not set (is .env present?)', file=sys.stderr)
        return 2

    conn = psycopg2.connect(url)
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    cur = conn.cursor()

    # The emails that have no recipient rows yet.
    cur.execute("""
        SELECT e.id, e.raw_email, e.recipient_id, u.email AS recipient_user_email
        FROM emails e
        LEFT JOIN users u ON u.id = e.recipient_id
        WHERE NOT EXISTS (SELECT 1 FROM email_recipients er WHERE er.email_id = e.id)
        ORDER BY e.id
    """)
    rows = cur.fetchall()
    total_candidates = len(rows)
    if args.limit:
        rows = rows[:args.limit]

    # The local users, so an address can be resolved the way the app does:
    # the user must exist AND be local.
    cur.execute("SELECT id, email FROM users WHERE is_local")
    local_users = {row['email'].lower(): row['id'] for row in cur.fetchall()}

    inserted = 0
    emails_touched = 0
    rows_written = 0
    with_headers = 0
    from_recipient_id = 0

    for row in rows:
        to_addrs, cc_addrs = parse_recipients(row['raw_email'])
        targets = []
        if to_addrs or cc_addrs:
            with_headers += 1
            for addr in to_addrs:
                targets.append(('to', addr))
            for addr in cc_addrs:
                targets.append(('cc', addr))
        elif row['recipient_id']:
            # No parseable headers: fall back to the primary recipient the
            # older code stored.
            from_recipient_id += 1
            targets.append(('to', row['recipient_user_email']))

        if not targets:
            continue

        values = []
        for rtype, addr in targets:
            if not addr:
                continue
            values.append((row['id'],
                           local_users.get(addr.lower()),
                           rtype,
                           addr))

        if not values:
            continue

        emails_touched += 1
        rows_written += len(values)
        if args.dry_run:
            continue

        for email_id, user_id, rtype, addr in values:
            cur.execute("""
                INSERT INTO email_recipients
                    (email_id, user_id, recipient_type, recipient_email)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (email_id, user_id, rtype, addr))
            inserted += cur.rowcount
    if not args.dry_run:
        conn.commit()
    cur.close()
    conn.close()

    mode = 'DRY RUN - nothing was written' if args.dry_run else 'written'
    print(f'email_recipients backfill ({mode})')
    print(f'  emails with no recipient rows : {total_candidates}'
          f'{" (processing the first %d)" % len(rows) if args.limit and args.limit < total_candidates else ""}')
    print(f'  emails that would be touched   : {emails_touched}')
    print(f'    recipients found in headers : {with_headers}')
    print(f'    fell back to recipient_id   : {from_recipient_id}')
    print(f'  recipient rows {mode:>15} : {rows_written}')
    if not args.dry_run:
        print(f'  rows actually inserted        : {inserted}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
