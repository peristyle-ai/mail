# Mail Server

A small local mail server with a REST API for local email management without SMTP.

## Tech Stack

- Python 3.8+
- Flask
- PostgreSQL
- JWT Authentication
- Swagger/OpenAPI Documentation

## Features

- **Authentication**: Register/login with JWT token-based authentication
- **Email Management**: Create, read, update, delete emails
- **Folders**: Organize emails with custom folders
- **Search**: Full-text search with filters (read/unread/starred, folder, pagination)
- **Attachments**: Upload and download file attachments (up to 10MB)
- **API Documentation**: Interactive Swagger UI at `/docs`
- **Security**: Protected endpoints, user data isolation, SQL injection prevention

## Setup

### 1. Prerequisites

- Python 3.8 or higher
- PostgreSQL 12 or higher
- pip

### 2. Clone and Setup Environment

```bash
# Clone the repository
git clone <repository-url>
cd mail-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Database Setup

```bash
# Create PostgreSQL database
createdb mail_server

# For testing
createdb mail_server_test
```

### 4. Environment Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your database credentials
nano .env
```

Your `.env` file should look like:
```
FLASK_APP=run.py
FLASK_ENV=development
DATABASE_URL=postgresql://username:password@localhost:5432/mail_server
JWT_SECRET=your-super-secret-key-change-this-in-production
HOST=127.0.0.1
```

### 5. Initialize Database Schema

```bash
python init_db.py
```

This creates all necessary tables (users, folders, emails, attachments, etc.).

### 6. Run the Server

**Option A: Flask API only (development)**
```bash
flask run
```

**Option B: Both Flask API + SMTP Server (recommended)**
```bash
python start_servers.py
```

This starts:
- Flask API on `http://localhost:5003`
- SMTP Server on port 2525

**Firewall Configuration** (if accessing from other computers):
```bash
sudo ufw allow 2525/tcp  # For SMTP server
sudo ufw allow 5001/tcp  # For Flask API (optional)
```

The server will start on `http://localhost:5003`

## API Documentation

### Interactive Documentation

Once the server is running, visit: **http://localhost:5003/docs**

This provides a Swagger UI where you can:
- Browse all available endpoints
- See request/response schemas
- Test endpoints directly in your browser
- View authentication requirements

### API Endpoints Overview

#### Authentication
- `POST /auth/register` - Register new user
- `POST /auth/login` - Login and get JWT token

#### Emails (requires JWT)
- `GET /api/emails` - List all emails
- `GET /api/emails/<id>` - Get specific email
- `POST /api/emails` - Create new email
- `POST /api/emails/<id>/read` - Mark as read
- `POST /api/emails/<id>/star` - Toggle starred
- `DELETE /api/emails/<id>` - Delete email
- `POST /api/emails/<id>/move` - Move to folder

#### Search (requires JWT)
- `GET /api/search?q=query&folder_id=1&flag=read&page=1&limit=20`

#### Attachments (requires JWT)
- `POST /api/emails/<id>/attachments` - Upload attachment
- `GET /api/emails/<id>/attachments` - List attachments
- `GET /api/attachments/<id>` - Download attachment
- `DELETE /api/attachments/<id>` - Delete attachment

#### Folders (requires JWT)
- `GET /api/folders` - List folders
- `POST /api/folders` - Create folder

### Authentication

All protected endpoints require a JWT token in the Authorization header:

```
Authorization: Bearer <your-jwt-token>
```

Get a token by registering and logging in:

```bash
# Register
curl -X POST http://localhost:5003/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "change-me-password", "name": "Test User"}'

# Login
curl -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "change-me-password"}'
```

## Testing

### Run All Tests

```bash
# Make sure test database exists
createdb mail_server_test

# Run tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_auth.py -v

# Run with coverage
pytest --cov=app tests/
```

### Test Structure

```
tests/
├── conftest.py           # Shared fixtures and configuration
├── test_auth.py          # Authentication tests (login, register, security)
├── test_emails.py        # Email CRUD and security tests
├── test_folders.py       # Folder management tests
├── test_search.py        # Search functionality tests
├── test_attachments.py   # Attachment upload/download tests
└── test_integration.py   # End-to-end integration tests
```

### Security Tests

The test suite includes comprehensive security tests:

- **Authentication**: Token validation, expired tokens, malformed tokens
- **Authorization**: Cross-user data access prevention
- **SQL Injection**: Tests in all user input fields
- **XSS**: Tests for script injection in email content
- **Input Validation**: Missing fields, invalid formats, extreme lengths
- **File Upload**: Type validation, size limits

## Security Considerations

1. **Password Storage**: Passwords are hashed using PBKDF2-SHA256
2. **JWT Tokens**: Tokens expire after 24 hours
3. **Data Isolation**: Users can only access emails in folders they own (JOIN folders f ON emails.folder_id = f.id WHERE f.user_id = current_user_id)
4. **SQL Injection**: All queries use parameterized statements
5. **File Uploads**: Restricted to allowed file types, max 10MB
6. **Environment Variables**: Sensitive data (JWT secret, DB credentials) stored in `.env` (not committed to git)

## Development

### Project Structure

```
.
├── app/
│   ├── __init__.py          # Flask app factory with Swagger
│   ├── db.py                # Database connection
│   ├── routes/
│   │   ├── auth.py          # Authentication endpoints
│   │   ├── emails.py        # Email endpoints
│   │   ├── folders.py       # Folder endpoints
│   │   ├── search.py        # Search endpoint
│   │   └── attachments.py   # Attachment endpoints
│   └── utils/
│       ├── auth.py          # JWT and password utilities
│       ├── db.py            # DB utilities
│       └── users.py         # User management
├── tests/                   # Comprehensive test suite
├── db/
│   └── schema.sql          # Database schema
├── .env.example            # Environment template
├── .env                    # Your environment (not in git)
├── requirements.txt        # Python dependencies
├── init_db.py             # Database initialization
└── run.py                 # Application entry point
```

### Adding New Endpoints

1. Add route in appropriate `app/routes/*.py` file
2. Add Swagger docstring for automatic documentation
3. Add comprehensive tests in `tests/`
4. Update API documentation

## Troubleshooting

### Database Connection Errors

```bash
# Check PostgreSQL is running
sudo service postgresql status

# Verify database exists
psql -l | grep mail_server
```

### Import Errors

```bash
# Make sure you're in the virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Test Failures

```bash
# Check test database exists and is accessible
psql -d mail_server_test -c "SELECT 1;"

# Run tests with more detail
pytest -v --tb=short
```

## License

MIT License - feel free to use this for personal or commercial projects.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## Future Enhancements

- [ ] Email threading/conversations
- [ ] Email templates
- [ ] Email forwarding
- [ ] Real-time notifications (WebSocket)
- [ ] Email import/export
- [ ] Admin dashboard
- [ ] Rate limiting on endpoints
- [ ] Password reset functionality
- [ ] Email encryption
