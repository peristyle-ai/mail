## Phase 5: Update Datetime Handling to Use Timezone-Aware Objects

## Overview
Migrate from deprecated `datetime.utcnow()` to timezone-aware datetime objects using `datetime.now(timezone.utc)`. Ensure consistency between Python code and PostgreSQL database.

---

## Goals
1. Replace all `datetime.utcnow()` calls with `datetime.now(timezone.utc)`
2. Update PostgreSQL schema to use `TIMESTAMP WITH TIME ZONE` instead of `TIMESTAMP`
3. Ensure all datetime handling is consistent across the application
4. Maintain backward compatibility with existing data

---

## Implementation Plan

### Step 1: Update Python Code
**Files to modify:**
- `app/utils/auth.py` - JWT token generation (exp, iat claims)
- `app/utils/users.py` - User creation timestamp
- Any other files using `datetime.utcnow()`

**Changes:**
- Import `timezone` from `datetime`
- Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`
- Update any datetime comparisons to handle timezone-aware objects

---

### Step 2: Update Database Schema
**Files to modify:**
- `db/schema.sql` - Update column types

**Changes:**
- Change `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` to `TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
- Update all tables: users, folders, emails, attachments, email_recipients

---

### Step 3: Create Migration Script
**New file:** `db/migrate_timezone.sql`

**Purpose:**
- Migrate existing data from TIMESTAMP to TIMESTAMP WITH TIME ZONE
- Handle conversion of existing timestamps to UTC
- Run as part of deployment

---

### Step 4: Update Test Database
**Actions:**
- Drop and recreate test database with new schema
- Verify all tests pass with timezone-aware datetimes

---

### Step 5: Verify and Test
**Actions:**
- Run full test suite
- Test JWT token generation/validation
- Verify database timestamps are stored correctly
- Check that API responses include timezone information

---

## Technical Details

### Python Changes
```python
# Before
from datetime import datetime, timedelta
now = datetime.utcnow()

# After
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
```

### PostgreSQL Changes
```sql
-- Before
CREATE TABLE users (
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- After
CREATE TABLE users (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Migration SQL
```sql
-- Convert existing tables
ALTER TABLE users 
    ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE,
    ALTER COLUMN updated_at TYPE TIMESTAMP WITH TIME ZONE;

-- Repeat for all tables with timestamp columns
```

---

## Files Checklist

### Code Files
- [ ] `app/utils/auth.py` - Update JWT datetime handling
- [ ] `app/utils/users.py` - Update user creation timestamp
- [ ] Search for any other `utcnow()` usage

### Database Files
- [ ] `db/schema.sql` - Update column definitions
- [ ] `db/migrate_timezone.sql` - Create migration script (new file)

### Test Files
- [ ] Run full test suite after changes
- [ ] Verify JWT tokens still work
- [ ] Check datetime serialization in API responses

---

## Potential Issues and Solutions

### Issue 1: Existing Data Conversion
**Problem:** Converting existing TIMESTAMP to TIMESTAMP WITH TIME ZONE
**Solution:** PostgreSQL assumes TIMESTAMP is in local timezone, need explicit conversion

### Issue 2: API Response Format
**Problem:** API responses may change format with timezone info
**Solution:** Ensure JSON serialization handles timezone-aware datetimes correctly

### Issue 3: JWT Token Compatibility
**Problem:** Existing tokens use utcnow(), new tokens use timezone-aware
**Solution:** Both should work since JWT uses Unix timestamps internally

---

## Success Criteria
- [ ] All `datetime.utcnow()` calls replaced with `datetime.now(timezone.utc)`
- [ ] Database schema uses `TIMESTAMP WITH TIME ZONE`
- [ ] All tests pass
- [ ] No deprecation warnings about datetime usage
- [ ] Existing data properly migrated

---

## Estimated Time
- Step 1 (Code): 20 minutes
- Step 2 (Schema): 10 minutes
- Step 3 (Migration): 15 minutes
- Step 4 (Testing): 20 minutes
- **Total: ~65 minutes**
