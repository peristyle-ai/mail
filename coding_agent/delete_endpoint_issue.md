# Mail Server API: Delete Endpoint Not Working - Bug Report

## Issue Summary

The `/api/emails/{id}` DELETE endpoint returns `{"status":"deleted"}` with HTTP 200, but emails are not actually deleted from the database.

## Evidence

### Test Case: Email ID 764

```bash
# 1. Delete the email
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "http://192.168.4.41:5003/api/emails/764"

# Response:
{"status":"deleted"}
# HTTP Status: 200

# 2. Verify deletion - email still exists!
curl -H "Authorization: Bearer $TOKEN" \
  "http://192.168.4.41:5003/api/emails/764"

# Response: Full email object returned (not 404)
{
  "id": 764,
  "subject": "test93",
  "body": "test\r\n",
  "folder_id": 47,
  ...
}

# 3. Check inbox list - email still appears
curl -H "Authorization: Bearer $TOKEN" \
  "http://192.168.4.41:5003/api/emails?folder_id=47&limit=5"

# Response includes:
{
  "id": 764,
  "subject": "test93"
}
```

## Expected Behavior

1. DELETE request returns `{"status":"deleted"}` with HTTP 200
2. Subsequent GET request for same email returns 404 `{"error": "Email not found"}`
3. Email no longer appears in email lists
4. Email is removed from database

## Actual Behavior

1. DELETE request returns `{"status":"deleted"}` with HTTP 200 ✅
2. Subsequent GET request returns full email object ❌
3. Email still appears in email lists ❌
4. Email remains in database ❌

## Possible Causes

### 1. Missing Transaction Commit

```python
# Possible issue in app/routes/emails.py
@emails_bp.route('/emails/<int:email_id>', methods=['DELETE'])
@require_auth
def delete_email(email_id):
    cursor = conn.cursor()
    cursor.execute("DELETE FROM emails WHERE id = %s", (email_id,))
    # Missing: conn.commit()  <-- THIS!
    return jsonify({'status': 'deleted'})
```

### 2. Wrong Database Connection

The delete might be executed on a different connection than the one used for queries.

### 3. Soft Delete Implementation

The endpoint might be implementing a "soft delete" (setting a `deleted_at` column) but queries don't filter out deleted emails.

### 4. Authorization Bypass

The endpoint might be returning success without actually executing the delete due to authorization checks.

### 5. Return Statement Before Commit

```python
# Possible issue
cursor.execute("DELETE FROM emails WHERE id = %s", (email_id,))
return jsonify({'status': 'deleted'})  # Returns before commit
conn.commit()  # Never reached
```

## Files to Check

| File | What to Check |
|------|---------------|
| `app/routes/emails.py` | DELETE endpoint implementation |
| `app/database.py` | Connection management and commit |
| `smtp_server/email_storage.py` | Email deletion methods |

## Suggested Fix

```python
@emails_bp.route('/emails/<int:email_id>', methods=['DELETE'])
@require_auth
def delete_email(email_id):
    user_id = g.user['id']
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Verify email belongs to user
    cursor.execute(
        "SELECT id FROM emails WHERE id = %s AND recipient_id = %s",
        (email_id, user_id)
    )
    
    if not cursor.fetchone():
        cursor.close()
        return jsonify({'error': 'Email not found'}), 404
    
    # Delete the email
    cursor.execute("DELETE FROM emails WHERE id = %s", (email_id,))
    
    # IMPORTANT: Commit the transaction
    conn.commit()
    cursor.close()
    
    return jsonify({'status': 'deleted'})
```

## Testing Steps

After fix, verify:

```bash
# 1. Get an email ID
EMAIL_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "http://192.168.4.41:5003/api/emails?limit=1" | jq '.[0].id')

# 2. Delete it
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "http://192.168.4.41:5003/api/emails/$EMAIL_ID"

# 3. Verify it's gone (should return 404)
curl -H "Authorization: Bearer $TOKEN" \
  "http://192.168.4.41:5003/api/emails/$EMAIL_ID"

# Expected: {"error": "Email not found"}
```

## Impact

**High Priority** - This affects core functionality:
- Users cannot delete emails from the web client
- Inbox becomes cluttered with unwanted emails
- Privacy/security concern: users expect deleted emails to be removed
- Storage bloat: emails accumulate without ability to remove

## Environment

- **Server**: Production (192.168.4.41:5003)
- **Database**: PostgreSQL
- **Endpoint**: `DELETE /api/emails/{id}`
- **Client**: py_pg_client (port 5005)

## Related

- Client delete route: `app/routes/emails.py:593-605`
- Client API wrapper: `app/api_client.py:86-88`
