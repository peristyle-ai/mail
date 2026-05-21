# Email Server Upgrade Specification
## Support for MIME Multipart Emails with Embedded Images

### Overview
The current email server at `localhost:5003` expects JSON payloads with simple HTML bodies. This causes raw MIME content to be sent as text when attempting to use multipart/related format for embedded images. This specification details the upgrade needed to properly support MIME multipart emails.

---

## Current Issue

When attempting to send emails with embedded images using MIME multipart format:

```python
# Current behavior (INCORRECT)
POST /api/emails
Body: {"to": "...", "subject": "...", "body": "Content-Type: multipart/related..."}

# Result: Email body contains raw MIME structure as text instead of properly 
# formatted email with inline images
```

The server receives:
```
Content-Type: multipart/related; boundary="==...=="
MIME-Version: 1.0
Subject: Brutto Daily 2026-02-17
From: the operator@example.com.au
To: payroll@example.com

--==...==
Content-Type: image/png
MIME-Version: 1.0
Content-Transfer-Encoding: base64
Content-ID: <coinbase_Testing_multi_plot>
Content-Disposition: inline; filename="coinbase_Testing_multi_plot.png"

iVBORw0KGgoAAAANSEUgAABkAAAAPoCAYAAACGezKDAAAAOXRFWHRTb2Z0d2FyZQBNYXRwbG90
bGliIHZlcnNpb24zLjYuMywgaHR0cHM6Ly9tYXRwbG90bGliLm9yZy/P9b71AAAACXBIWXMAAA9h
...
```

Instead of a properly rendered email with inline images.

---

## Required Functionality

### 1. New API Endpoint: `/api/emails/mime`

**Method:** `POST`

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**
```json
{
  "to": "recipient@example.com",
  "mime_content": "Content-Type: multipart/related; boundary=\"==...==\"\nMIME-Version: 1.0\nSubject: Report\nFrom: sender@example.com\nTo: recipient@example.com\n\n--==...==\nContent-Type: text/html; charset=utf-8\n\n<html>...</html>\n--==...==\nContent-Type: image/png\nContent-ID: <plot1>\nContent-Disposition: inline; filename=\"plot1.png\"\n\niVBORw0KGgo...\n--==...==--"
}
```

**Response:**
```json
{
  "id": 123,
  "queued": true,
  "status": "pending"
}
```

**Error Response:**
```json
{
  "error": "Invalid MIME content",
  "details": "Failed to parse MIME message: missing boundary"
}
```

---

### 2. Alternative: Enhanced `/api/emails` with attachments

**Method:** `POST`

**Content-Type:** `multipart/form-data` (instead of `application/json`)

**Form Fields:**
- `to`: Recipient email address (string, required)
- `subject`: Email subject (string, required)
- `html`: HTML content with `cid:` references (string, required)
- `attachments`: One or more image files (file, optional)
- `content_ids`: JSON array mapping filenames to Content-IDs (string, optional)
  Example: `{"coinbase_plot.png": "plot1", "kraken_plot.png": "plot2"}`

**Example Request:**
```http
POST /api/emails
Authorization: Bearer <JWT_TOKEN>
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

------WebKitFormBoundary
Content-Disposition: form-data; name="to"

recipient@example.com
------WebKitFormBoundary
Content-Disposition: form-data; name="subject"

Daily Report
------WebKitFormBoundary
Content-Disposition: form-data; name="html"

<html><body><img src="cid:plot1"></body></html>
------WebKitFormBoundary
Content-Disposition: form-data; name="attachments"; filename="coinbase_plot.png"
Content-Type: image/png

<binary image data>
------WebKitFormBoundary
Content-Disposition: form-data; name="content_ids"

{"coinbase_plot.png": "plot1"}
------WebKitFormBoundary--
```

**Response:** Same as current endpoint

---

## Implementation Details

### Option 1: Parse Raw MIME (Recommended)

**Python Implementation:**

```python
from email import message_from_string
from email.mime.multipart import MIMEMultipart
from email.parser import Parser

def send_mime_email(request):
    """Handle MIME email endpoint"""
    mime_content = request.json['mime_content']
    
    # Parse the MIME message
    msg = message_from_string(mime_content)
    
    # Validate structure
    if not msg.is_multipart():
        return error_response("Message must be multipart")
    
    # Extract components
    to_address = msg['To']
    subject = msg['Subject']
    from_address = msg['From']
    
    # Send via SMTP or your current email mechanism
    # The key is to preserve the multipart structure
    smtp_server.send_message(msg)
    
    return success_response(email_id)
```

**Key Requirements:**
1. Parse incoming `mime_content` using Python's `email` library
2. Validate that it's a valid MIME multipart message
3. Preserve all headers (From, To, Subject, Content-Type boundaries)
4. Pass the entire parsed message to your email delivery system
5. Do NOT treat it as plain text body content

### Option 2: Build MIME from Parts

If accepting raw MIME is problematic, accept structured data and construct the MIME:

```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

def send_email_with_attachments(request):
    """Build MIME email from parts"""
    # Create multipart message
    msg = MIMEMultipart('related')
    msg['Subject'] = request.form['subject']
    msg['From'] = sender_email
    msg['To'] = request.form['to']
    
    # Attach HTML
    html_part = MIMEText(request.form['html'], 'html', 'utf-8')
    msg.attach(html_part)
    
    # Attach images
    for uploaded_file in request.files.getlist('attachments'):
        img_data = uploaded_file.read()
        mime_type = uploaded_file.content_type
        filename = uploaded_file.filename
        
        image_part = MIMEImage(img_data, _subtype=mime_type.split('/')[-1])
        content_id = request.form.get('content_ids', {}).get(filename, filename)
        
        image_part.add_header('Content-ID', f'<{content_id}>')
        image_part.add_header('Content-Disposition', 'inline', filename=filename)
        msg.attach(image_part)
    
    # Send
    smtp_server.send_message(msg)
```

---

## HTML Structure Requirements

The HTML sent should reference images using `cid:` protocol:

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Daily Report</title>
</head>
<body>
    <h1>Brutto Daily Summary</h1>
    <img src="cid:coinbase_Testing_multi_plot" width="600">
    <img src="cid:kraken_testing_multi_plot" width="600">
</body>
</html>
```

**Important:**
- Use `cid:` prefix without angle brackets in HTML
- Match Content-ID exactly (including case)
- Content-ID in MIME part should include angle brackets: `<coinbase_Testing_multi_plot>`

---

## Testing

### Test Case 1: Simple HTML Email
```bash
curl -X POST http://localhost:5003/api/emails/mime \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "test@example.com",
    "mime_content": "Content-Type: multipart/related; boundary=\"==test==\"\nMIME-Version: 1.0\nSubject: Test\nFrom: sender@example.com\nTo: test@example.com\n\n--==test==\nContent-Type: text/html; charset=utf-8\n\n<html><body>Test</body></html>\n--==test==--"
  }'
```

### Test Case 2: Email with Image
Create a test with:
1. HTML containing `<img src="cid:test_plot">`
2. Image attachment with `Content-ID: <test_plot>`
3. Verify image displays inline

### Test Case 3: Multiple Images
Verify multiple `cid:` references all resolve correctly.

---

## Client-Side Usage (Python)

Example of how the live_trading project will use the new endpoint:

```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

def send_email_with_images(subject, html_path, images_dir, to):
    # Create MIME message
    msg = MIMEMultipart('related')
    msg['Subject'] = subject
    msg['From'] = EMAIL
    msg['To'] = to
    
    # Read HTML
    with open(html_path, 'r') as f:
        html_content = f.read()
    
    # Find and replace image references
    for img_file in Path(images_dir).glob('*.png'):
        content_id = img_file.stem
        
        # Attach image
        with open(img_file, 'rb') as f:
            img_part = MIMEImage(f.read())
        
        img_part.add_header('Content-ID', f'<{content_id}>')
        img_part.add_header('Content-Disposition', 'inline', filename=img_file.name)
        msg.attach(img_part)
        
        # Update HTML to use cid:
        html_content = html_content.replace(str(img_file.name), f'cid:{content_id}')
    
    # Attach HTML
    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)
    
    # Send via new API
    response = requests.post(
        'http://localhost:5003/api/emails/mime',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'to': to,
            'mime_content': msg.as_string()
        }
    )
    
    return response.json()
```

---

## Success Criteria

1. ✅ Raw MIME content is properly parsed (not treated as text body)
2. ✅ HTML with `cid:` references displays images inline
3. ✅ Email clients (Gmail, Outlook, Apple Mail) show embedded images correctly
4. ✅ Multiple images can be embedded in single email
5. ✅ Images are not displayed as attachments (unless explicitly requested)
6. ✅ Backward compatibility maintained with existing `/api/emails` endpoint

---

## Priority

**HIGH** - This is blocking the proper display of charts/plots in daily summary emails.

## Estimated Effort

- **Option 1 (Parse MIME):** 2-4 hours
- **Option 2 (Build MIME):** 4-6 hours

**Recommendation:** Start with Option 1 (Parse MIME) as it's simpler and more flexible.

---

## Questions?

Contact: User is working on `live_trading` project at `~/git/live_trading`
Current implementation: `utils/email_sender.py`