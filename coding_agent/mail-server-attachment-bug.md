# Mail Server API Bug: Attachment Listing Endpoint Returns Empty for MIME-Embedded Attachments

## Summary

The `/api/emails/{email_id}/attachments` API endpoint returns an empty list for emails that were created with attachments via `/api/emails/mime`, even though the attachments are successfully delivered to recipients.

## Reproduction Steps

1. Create an email with an attachment using `/api/emails/mime` endpoint:

```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

msg = MIMEMultipart()
msg['From'] = sender_email
msg['To'] = 'recipient@example.com'
msg['Subject'] = 'Test with PDF'

msg.attach(MIMEText('Test body', 'plain'))

# Add attachment
attachment = MIMEBase('application', 'pdf')
attachment.set_payload(pdf_bytes)
encoders.encode_base64(attachment)
attachment.add_header('Content-Disposition', 'attachment', filename='document.pdf')
msg.attach(attachment)

# Send via /api/emails/mime
payload = {
    'to': 'recipient@example.com',
    'subject': 'Test with PDF',
    'mime_content': msg.as_string()  # Raw MIME string, NOT base64
}
POST to /api/emails/mime with Content-Type: application/json
```

2. Email is created successfully and recipient receives the email WITH the PDF attachment.

3. Query `/api/emails/{email_id}/attachments` to list attachments:

```python
GET /api/emails/903/attachments
# Returns: []
```

4. Also, the email object from `/api/emails/{email_id}` shows no attachments field or empty attachments:

```json
{
  "id": 903,
  "subject": "Test with PDF",
  ...
  // No "attachments" field or "attachments": []
}
```

## Expected Behavior

- `/api/emails/{email_id}/attachments` should return metadata about attachments embedded via MIME
- Email object should include `attachments` array with attachment details

## Actual Behavior

- `/api/emails/mime` successfully creates and delivers emails with attachments
- `/api/emails/{email_id}/attachments` returns empty list
- Email object has no attachment metadata

## Impact

- Cannot programmatically verify attachment presence after sending
- Cannot retrieve/download attachments via API
- Attachment listing UI would show no attachments for valid emails

## Root Cause Hypothesis

The `/api/emails/mime` endpoint likely:
1. Parses MIME content correctly for delivery
2. Does NOT persist attachment metadata to the database
3. The `/api/emails/{email_id}/attachments` endpoint queries a table/collection that was never populated

## Suggested Fix

### Option A: Persist attachment metadata during MIME processing

In the `/api/emails/mime` handler, after parsing the MIME message:

```python
# Pseudocode
def create_email_from_mime(mime_content, to, subject):
    msg = email.message_from_string(mime_content)
    
    # Extract and save attachments
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get('Content-Disposition') is None:
            continue
        
        filename = part.get_filename()
        if filename:
            # Save attachment to storage/database
            attachment_id = save_attachment(
                email_id=email_id,
                filename=filename,
                content_type=part.get_content_type(),
                content=part.get_payload(decode=True)
            )
            attachments.append(attachment_id)
    
    # Also store email body
    body = extract_body(msg)
    
    # Save to database
    email = Email.create(
        to=to,
        subject=subject,
        body=body,
        attachments=attachments  # Store attachment IDs
    )
    return email
```

### Option B: Parse attachments on-demand when listing

Alternatively, store the raw MIME and parse it when `/api/emails/{id}/attachments` is called:

```python
def get_email_attachments(email_id):
    email = Email.get(email_id)
    if not email.mime_content:
        return []
    
    msg = email.message_from_string(email.mime_content)
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        filename = part.get_filename()
        if filename:
            attachments.append({
                'id': generate_attachment_id(email_id, filename),
                'filename': filename,
                'content_type': part.get_content_type(),
                'size': len(part.get_payload(decode=True))
            })
    return attachments
```

## Test Cases to Add

1. **POST /api/emails/mime with attachment** → verify email is created
2. **GET /api/emails/{id}/attachments** → should return attachment list
3. **GET /api/attachments/{attachment_id}** → should download attachment
4. **POST /api/emails/{id}/attachments** (upload endpoint) → should also work for non-MIME emails

## Environment

- Server: `http://192.168.4.41:5003`
- Endpoint affected: `/api/emails/{email_id}/attachments`
- MIME endpoint: `/api/emails/mime`
- Verified: 2026-03-19

## Workaround

For now, the API consumer can:
- Use `/api/emails/mime` for sending attachments (it works for delivery)
- Accept that attachment listing via API is unreliable
- Store attachment metadata separately if needed for application logic