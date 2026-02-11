## Phase 4: Testing & Documentation (IN PROGRESS)

## Goals
1. Fix auth bugs and expand test coverage
2. Add OpenAPI/Swagger documentation with interactive UI
3. Create .env.example and verify setup
4. Comprehensive security testing
5. Automated test suite for CI/CD

---

### 1. FIX AUTH BUGS (Priority: High)
**Bug in `/opt/py_pg_accounts/git/py_pg_email/app/routes/auth.py`:**
- Line 38: `hash_password(password) != user['password_hash']` compares two hashed passwords
- Issue: Each call to `hash_password()` produces a different result due to salt
- **Fix:** Need to use `verify_password()` or compare hashes properly

**Tasks:**
- [ ] Review `/opt/py_pg_accounts/git/py_pg_email/app/utils/auth.py` to see password verification logic
- [ ] Fix password comparison in auth.py line 38
- [ ] Verify JWT token generation/validation works

---

### 2. UNIT TEST EXPANSION
**File: `/opt/py_pg_accounts/git/py_pg_email/tests/test_app.py`**

**Auth Tests:**
- [ ] Fix existing register test
- [ ] Fix existing login test  
- [ ] Add token validation test (protected endpoint access)
- [ ] Add duplicate registration test (409 error)
- [ ] Add invalid credentials test (401 error)

**Email CRUD Tests:**
- [ ] Test POST /api/emails (create email)
- [ ] Test GET /api/emails (list emails)
- [ ] Test GET /api/emails/<id> (get specific email)
- [ ] Test POST /api/emails/<id>/read (mark as read)
- [ ] Test POST /api/emails/<id>/star (toggle starred)
- [ ] Test POST /api/emails/<id>/move (move to folder)
- [ ] Test DELETE /api/emails/<id> (delete email)

**Search Tests:**
- [ ] Test GET /api/search?q=query (basic search)
- [ ] Test search with folder_id filter
- [ ] Test search with flag filter (read/unread/starred)
- [ ] Test search pagination (page, limit)

**Attachment Tests:**
- [ ] Test POST /api/emails/<id>/attachments (upload)
- [ ] Test GET /api/emails/<id>/attachments (list)
- [ ] Test GET /api/attachments/<id> (download)
- [ ] Test DELETE /api/attachments/<id> (delete)
- [ ] Test file size limit (10MB)
- [ ] Test allowed file types

**Folder Tests:**
- [ ] Test GET /api/folders (list folders)
- [ ] Test POST /api/folders (create folder)

---

### 3. SECURITY TESTS

**Authentication Security:**
- [ ] Test password hashing uses bcrypt/secure algorithm
- [ ] Test JWT tokens expire after reasonable time
- [ ] Test expired JWT tokens are rejected
- [ ] Test malformed JWT tokens are rejected
- [ ] Test protected endpoints require valid JWT
- [ ] Test SQL injection prevention in all user inputs
- [ ] Test XSS prevention in email content

**Authorization Security:**
- [ ] Test users cannot access other users' emails
- [ ] Test users cannot delete other users' emails
- [ ] Test users cannot access other users' attachments
- [ ] Test users cannot create folders for other users
- [ ] Test folder access is restricted to owner

**Input Validation:**
- [ ] Test missing required fields return proper errors
- [ ] Test invalid email format is rejected
- [ ] Test extremely long inputs are handled/limited
- [ ] Test special characters in inputs don't break queries
- [ ] Test file upload validation (type, size)

**Rate Limiting:**
- [ ] Consider adding rate limiting to auth endpoints
- [ ] Test brute force protection on login

---

### 4. INTEGRATION TESTS

**End-to-End Workflow:**
- [ ] Register → Login → Create Email → Search → Delete
- [ ] Full user lifecycle with assertions at each step

**Folder Management:**
- [ ] Create folder → Create email in folder → Move email between folders → Delete folder

**Attachment Workflow:**
- [ ] Create email → Upload attachment → Download attachment → Delete attachment → Delete email

**Cross-User Security:**
- [ ] User A cannot access User B's data
- [ ] User A cannot modify User B's emails
- [ ] Test isolation between user sessions

---

### 5. DOCUMENTATION

**.env.example Creation:**
- [ ] Create `/opt/py_pg_accounts/git/py_pg_email/.env.example` with placeholder values:
  ```
  FLASK_APP=run.py
  FLASK_ENV=development
  DATABASE_URL=postgresql://username:password@localhost:5432/mail_server
  JWT_SECRET=your-secret-key-here
  ```

**OpenAPI/Swagger Documentation:**
- [ ] Add `flasgger` to requirements.txt
- [ ] Install flasgger package
- [ ] Add Swagger UI endpoint at `/docs`
- [ ] Add OpenAPI spec at `/api/spec.json`
- [ ] Document all endpoints with:
  - Request/response schemas
  - Authentication requirements
  - Example requests
  - Error responses

**README Updates:**
- [ ] Update setup instructions with `.env.example` info
- [ ] Add Swagger UI usage instructions
- [ ] Add testing instructions
- [ ] Add security considerations section

---

### 6. SETUP VERIFICATION

**Health Check:**
- [ ] Verify GET /health endpoint exists and works
- [ ] Add if missing

**Database Schema Check:**
- [ ] Verify `emails` table uses `user_id` vs `sender_id` consistency with routes
- [ ] Check if default folders (Inbox, Sent, Drafts, Trash) are created automatically

**Test Database Setup:**
- [ ] Verify test database configuration works
- [ ] Add test setup/teardown to clean database between tests
- [ ] Create `tests/conftest.py` with shared fixtures

**Run All Tests:**
- [ ] Fix any failing tests
- [ ] Achieve >80% coverage if possible
- [ ] Document test commands

---

### Success Criteria
- [ ] All auth tests pass
- [ ] All email CRUD tests pass
- [ ] All search tests pass
- [ ] All attachment tests pass
- [ ] All security tests pass (isolation, injection, auth)
- [ ] Swagger UI accessible at `/docs`
- [ ] `.env.example` created and documented
- [ ] README updated with complete setup and testing instructions
- [ ] No critical bugs in auth or core functionality
- [ ] Tests can run via `pytest` command for CI/CD

---

### Progress Tracking
*Update checkboxes as tasks complete*

**Current Status:** Starting Phase 4 completion
**Estimated Time:** 2-3 hours
**Blockers:** None identified yet
