# Mail Server

A small local mail server with a REST API for local email management without SMTP.

## Tech Stack

- Python
- Flask
- PostgreSQL

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file with:
```
FLASK_APP=run.py
FLASK_ENV=development
DATABASE_URL=postgresql://localhost/mailserver
```

3. Initialize database:
```bash
python init_db.py
```

4. Run server:
```bash
flask run
```

## API Endpoints

### Health Check
- `GET /health` - Health check

### Emails
- `GET /api/emails` - List all emails
- `GET /api/emails/<id>` - Get email by ID
- `POST /api/emails` - Create email (sender_id, subject, body, headers, folder_id)

### Folders
- `GET /api/folders?user_id=<id>` - List folders for user
- `POST /api/folders` - Create folder (user_id, name, parent_id)
