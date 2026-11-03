-- =============================================================================
-- Migration 009: Default user timezone to Australia/Brisbane
-- =============================================================================
--
-- The `users.timezone` column defaulted to 'Australia/Sydney'. Brisbane is
-- UTC+10 with no daylight saving; Sydney is UTC+11 for roughly half the
-- year. Every timestamp the webmail client rendered used the account's
-- timezone, so from late September to early April every time in the UI --
-- and every quoted "On <date>" line in a sent reply -- was one hour ahead
-- of the actual local time.
--
-- No endpoint lets a user choose a timezone, so this column default was the
-- only value most accounts ever had: 105 of 109 local accounts were on
-- Sydney, purely by inheritance of the default. Setting the column default
-- alone would therefore not have fixed existing accounts; the UPDATE below
-- is the part that matters.
--
-- Run as: DB owner (postgres or mal_external)
--   psql -U <owner> -h localhost -d mail_server -f db/migrations/008_user_timezone_brisbane.sql
--
-- Idempotent: conditional DDL, and the UPDATE only touches rows still on
-- the old default.
-- =============================================================================

-- The column is absent from the canonical schema on some installs; add it
-- with the correct default if so.
ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'Australia/Brisbane';

-- New rows get the right default from now on.
ALTER TABLE users ALTER COLUMN timezone SET DEFAULT 'Australia/Brisbane';

-- Existing accounts that inherited the old default.
UPDATE users SET timezone = 'Australia/Brisbane' WHERE timezone = 'Australia/Sydney';
