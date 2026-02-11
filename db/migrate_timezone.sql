-- Migration script to convert existing TIMESTAMP columns to TIMESTAMP WITH TIME ZONE
-- This assumes your server timezone is UTC or you want to convert to UTC

-- Convert users table
ALTER TABLE users 
    ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC',
    ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE USING updated_at AT TIME ZONE 'UTC';

-- Convert folders table
ALTER TABLE folders 
    ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';

-- Convert emails table
ALTER TABLE emails 
    ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';

-- Convert attachments table
ALTER TABLE attachments 
    ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';

-- Update indexes
DROP INDEX IF EXISTS idx_emails_created;
CREATE INDEX idx_emails_created ON emails(created_at);

-- Verify the changes
SELECT 
    table_name, 
    column_name, 
    data_type 
FROM information_schema.columns 
WHERE table_schema = 'public' 
AND column_name IN ('created_at', 'updated_at')
ORDER BY table_name, column_name;
