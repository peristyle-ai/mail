"""
Database init script for the mail server.

Mode-aware install:
  --mode=schema     Install as a PostgreSQL schema in an existing DB.
                    Default MAIL_SCHEMA=mail. The schema is created if it
                    doesn't exist. Tables are installed into the schema.
                    USE THIS FOR PER-CUSTOMER PER-DB INSTALLS.
  --mode=standalone Create tables in the DB public schema. Default
                    MAIL_SCHEMA=public. The DB itself must already exist
                    (e.g. via `createdb mail_server`).
                    USE THIS FOR THE LEGACY SINGLE-DB SHARED MAIL SERVER.

Environment:
  DATABASE_URL    Postgres connection URL (required)
  MAIL_SCHEMA     Schema to install into (default: public)
  MAIL_USERS_TABLE
                  Fully-qualified users table name (default: <MAIL_SCHEMA>.users).
                  In v0.3 the external-table opt-in is asserted but not enforced.
                  For v0.4+, the mail server will read/write only password_hash
                  and api_key on the external table.

Examples:
  # Customer (per-customer, schema mode)
  DATABASE_URL=postgresql://customer@127.0.0.1:5432/customer \
      MAIL_SCHEMA=mail \
      python3 init_db.py --mode=schema

  # Legacy shared server
  DATABASE_URL=postgresql://mail_external@127.0.0.1:5432/mail_server \
      MAIL_SCHEMA=public \
      python3 init_db.py --mode=standalone
"""

import os
import sys
import glob
import psycopg2
from dotenv import load_dotenv
from config import mail_config  # Phase 1d: respect MAIL_SCHEMA config

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')


def _parse_args():
    """Minimal argv parser. --mode=schema (default) | --mode=standalone."""
    mode = "schema"  # default for v0.3
    for arg in sys.argv[1:]:
        if arg == "--mode=schema":
            mode = "schema"
        elif arg == "--mode=standalone":
            mode = "standalone"
        elif arg in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"Unknown argument: {arg!r}. Use --mode=schema (default) or --mode=standalone.", file=sys.stderr)
            sys.exit(2)
    return mode


def _assert_external_users_table(cursor, users_table: str, mail_schema: str):
    """v0.3: assert the external MAIL_USERS_TABLE exists with the required columns.

    v0.4+ will actually use this table for auth. For v0.3 we just sanity-check
    and proceed. The mail server still creates its own <MAIL_SCHEMA>.users.

    Required columns: id (SERIAL or INTEGER), email, password_hash.
    """
    if users_table == f"{mail_schema}.users":
        # default — no external table check needed
        return
    print(f"[1d] MAIL_USERS_TABLE is set to {users_table!r} (external).")
    print(f"[1d] v0.3 NOTE: the external-users-table code path is deferred to v0.4+.")
    print(f"[1d] For v0.3, the mail server still uses <{mail_schema}>.users for auth.")
    print(f"[1d] v0.3 only checks that the external table exists and has the right columns.")
    try:
        schema_name, table_name = users_table.split(".", 1)
    except ValueError:
        print(f"[1d] ERROR: MAIL_USERS_TABLE={users_table!r} is not fully-qualified (expected 'schema.table').", file=sys.stderr)
        sys.exit(3)
    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema_name, table_name),
    )
    columns = {row[0] for row in cursor.fetchall()}
    if not columns:
        print(f"[1d] ERROR: external users table {users_table!r} does not exist.", file=sys.stderr)
        print(f"[1d] The mail server will not create it. The owner of {users_table!r} must create it first.", file=sys.stderr)
        sys.exit(4)
    required = {"id", "email", "password_hash"}
    missing = required - columns
    if missing:
        print(f"[1d] ERROR: external users table {users_table!r} is missing required columns: {sorted(missing)}", file=sys.stderr)
        sys.exit(5)
    print(f"[1d] OK: external users table {users_table!r} has the required columns.")


def _ensure_schema(cursor, schema: str):
    """Create the schema if it doesn't exist (schema mode only)."""
    if schema == "public":
        # public schema is always there
        return
    cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    print(f"[1d] ensured schema {schema!r} exists")


def init_db(mode: str = "schema"):
    """Initialise the mail server database.

    Reads MAIL_SCHEMA from the config (env-overridable, default 'public'),
    sets the search_path, and applies all SQL files in db/ in alphabetical order.
    """
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable is not set. Set it in .env.", file=sys.stderr)
        sys.exit(1)

    schema = mail_config.mail_schema
    users_table = mail_config.mail_users_table

    if mode == "standalone" and schema != "public":
        print(f"WARN: --mode=standalone with MAIL_SCHEMA={schema!r}; ignoring and installing into {schema!r} anyway.", file=sys.stderr)
    if mode == "schema" and schema == "public":
        print(f"WARN: --mode=schema with MAIL_SCHEMA=public; this is the legacy default. Did you mean MAIL_SCHEMA=mail?", file=sys.stderr)

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    print(f"[1d] mode={mode!r}, MAIL_SCHEMA={schema!r}, MAIL_USERS_TABLE={users_table!r}")

    # Ensure the schema exists (schema mode only; public is always there)
    if mode == "schema":
        _ensure_schema(cursor, schema)

    # Set the search_path so unqualified CREATE TABLE statements install into
    # the configured schema. This is the backward-compat path: when MAIL_SCHEMA
    # is unset (= 'public'), the rendered behaviour is identical to the old
    # init_db.py.
    cursor.execute(f'SET search_path TO "{schema}", public')
    print(f"[1d] set search_path to {schema!r}, public")
    
    # Set the mail_schema GUC so migrations can reference it for verification
    cursor.execute(f"SET app.mail_schema = '{schema}'")
    print(f"[1d] set app.mail_schema GUC to {schema!r}")

    # Check the external users table if MAIL_USERS_TABLE was set
    _assert_external_users_table(cursor, users_table, schema)

    # Apply all SQL files in db/ in alphabetical order. This is the same as
    # the old init_db.py but generalised: it picks up any new SQL files added
    # to db/ in the future without needing to edit this script.
    sql_files = sorted(glob.glob("db/*.sql"))
    if not sql_files:
        print("ERROR: no .sql files found in db/", file=sys.stderr)
        sys.exit(6)
    for sql_file in sql_files:
        print(f"[1d] applying {sql_file} ...")
        with open(sql_file, "r") as f:
            sql = f.read()
        try:
            cursor.execute(sql)
            conn.commit()  # Commit after each file so partial progress is kept
        except Exception as e:
            print(f"[1d] ERROR in {sql_file}: {e}")
            conn.rollback()
            raise

    # Apply migrations from db/migrations/ in order (002, 003, etc.)
    # These are incremental schema changes that assume the base tables exist.
    # Some migrations require superuser (e.g. CREATE EXTENSION vector) —
    # those are skipped with a warning if the current role lacks privileges.
    migration_files = sorted(glob.glob("db/migrations/*.sql"))
    if migration_files:
        print(f"[1d] applying {len(migration_files)} migrations from db/migrations/ ...")
        for migration_file in migration_files:
            print(f"[1d] applying {migration_file} ...")
            with open(migration_file, "r") as f:
                sql = f.read()
            try:
                cursor.execute(sql)
                conn.commit()  # Commit after each migration
            except psycopg2.errors.InsufficientPrivilege as e:
                print(f"[1d] WARNING: skipped {migration_file} (insufficient privilege: {e})")
                print(f"[1d]   This migration requires superuser. Run manually as postgres if needed.")
                conn.rollback()  # Roll back only the failed migration
                continue
            except Exception as e:
                print(f"[1d] ERROR in {migration_file}: {e}")
                conn.rollback()
                raise

    # The rate-limit-attempts table is created in-line (not in a .sql file) so
    # we can keep the structure visible here. This matches the old init_db.py.
    print("[1d] creating rate_limit_attempts (if not exists)...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rate_limit_attempts (
            id SERIAL PRIMARY KEY,
            key VARCHAR(500) NOT NULL,
            attempted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_rate_limit_attempts_key
        ON rate_limit_attempts(key)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_rate_limit_attempts_time
        ON rate_limit_attempts(attempted_at)
    ''')

    conn.commit()
    cursor.close()
    conn.close()

    print(f"[1d] OK: {mode} install into {schema!r} complete (users table: {users_table!r}).")
    if mode == "schema":
        print(f"[1d]     the schema {schema!r} now has the mail server's tables.")
        print(f"[1d]     no other schema in this DB was touched.")
    print(f"[1d]     next: start the mail server with DATABASE_URL pointing at this DB.")


if __name__ == '__main__':
    mode = _parse_args()
    init_db(mode=mode)
