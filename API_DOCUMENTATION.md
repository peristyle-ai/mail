# Mail Server - API Documentation

## Overview
REST API for email management with JWT authentication

## Base URL
`http://localhost:5000`

## Authentication
All protected endpoints require JWT token in header:
```
Authorization: Bearer <token>
```

## Endpoints

### Authentication

#### Register
`POST /auth/register`
```json
{
    "email": "user@example.com",
    "password": "password123",
    "name": "User Name"
}
```

#### Login
`POST /auth/login`
```json
{
    "email": "user@example.com",
    "password": "password123"
}
```
Response:
```json
{
    "token": "jwt_token_here",
    "user": {"id": 1, "email": "user@example.com"}
}
```

### Emails

#### List Emails
`GET /api/emails`
Returns all emails for authenticated user

#### Get Email
`GET /api/emails/<id>`

#### Create Email
`POST /api/emails`
```json
{
    "to": "recipient@example.com",
    "subject": "Subject",
    "body": "Email body",
    "folder_id": 1
}
```

#### Mark as Read
`POST /api/emails/<id>/read`

#### Toggle Starred
`POST /api/emails/<id>/star`

#### Delete Email
`DELETE /api/emails/<id>`

#### Move Email
`POST /api/emails/<id>/move`
```json
{
    "folder_id": 2
}
```

### Search
`GET /api/search?q=search_terms&folder_id=1&flag=read`
Query params:
- `q`: Search query
- `folder_id`: Filter by folder
- `flag`: Filter by flag (read, unread, starred)
- `page`: Page number
- `limit`: Results per page

### Attachments

#### Upload
`POST /api/emails/<id>/attachments`
Multipart form data with `file` field

#### List Attachments
`GET /api/emails/<id>/attachments`

#### Download
`GET /api/attachments/<id>`

#### Delete
`DELETE /api/attachments/<id>`

### Folders
`GET /api/folders`

## Setup
1. Copy `.env.example` to `.env`
2. Configure database connection
3. Run migrations
4. `python run.py`

## Testing
`pytest tests/`
