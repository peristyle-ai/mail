---
name: reply-invite
description: Accept or decline meeting invites (VCALENDAR/text/calendar) received via email. Use when the user needs to respond to a meeting invitation that arrived as an email with a calendar attachment.
version: 1.0.0
metadata:
  openclaw:
    requires:
      env:
        - EMAIL_SERVER
        - EMAIL_ADDRESS
        - EMAIL_PASSWORD
      bins: []
    primaryEnv: EMAIL_ADDRESS
    emoji: "📅"
    homepage: https://github.com/peristyle-ai/mail
    tags:
      - email
      - calendar
      - meeting
      - invite
---

# Reply to Meeting Invite Skill

Use this skill to accept or decline meeting invites received via email. The invite arrives as a `text/calendar` MIME part (VCALENDAR format) inside an email.

## How It Works

Meeting invites from Outlook, Google Calendar, etc. contain a `text/calendar` MIME part with a VCALENDAR payload. To accept or decline, you send a reply email with:

1. **Same subject** prefixed with `Accepted:` or `Declined:`
2. **Updated VCALENDAR** with `METHOD:REPLY` and `PARTSTAT:ACCEPTED` (or `DECLINED`)
3. **Threading headers** (`In-Reply-To`, `References`) to link to the original

## Quick Start

```python
from skills.local-email.scripts.mail_api import MailAPI

api = MailAPI()

# 1. Find the meeting invite email
emails = api.search_emails("subject:meeting")
invite = emails[0]

# 2. Extract the calendar content
# The API now includes 'calendar' field for meeting invites
cal_content = invite.get('calendar')
if not cal_content:
    # Fallback: parse from raw_email
    from email import policy
    from email.parser import BytesParser
    msg = BytesParser(policy=policy.default).parsebytes(invite['raw_email'].encode())
    for part in msg.walk():
        if part.get_content_type() == 'text/calendar':
            cal_content = part.get_content()
            break

# 3. Parse the VCALENDAR to get UID and SEQUENCE
import re
uid = re.search(r'UID:([^\r\n]+)', cal_content).group(1)
sequence = int(re.search(r'SEQUENCE:(\d+)', cal_content).group(1))

# 4. Build the acceptance VCALENDAR
from datetime import datetime, timezone
dtstamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

accept_cal = f'''BEGIN:VCALENDAR
METHOD:REPLY
PRODID:Microsoft Exchange Server 2010
VERSION:2.0
BEGIN:VEVENT
UID:{uid}
SEQUENCE:{sequence + 1}
DTSTAMP:{dtstamp}
ORGANIZER;CN=Organizer Name:mailto:organizer@example.com
ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN=you@example.com:mailto:you@example.com
SUMMARY;LANGUAGE=en-US:Accepted: Original Meeting Subject
END:VEVENT
END:VCALENDAR'''

# 5. Send the reply
api.send_email(
    to='organizer@example.com',
    subject=f"Accepted: {invite['subject']}",
    body='I accept the meeting invitation.',
    in_reply_to=invite['message_id'],
    references=f"{invite.get('references_chain', '')} {invite['message_id']}".strip(),
)
```

## VCALENDAR Reply Format

### Accept
```
METHOD:REPLY
PARTSTAT:ACCEPTED
```

### Decline
```
METHOD:REPLY
PARTSTAT:DECLINED
```

### Tentative
```
METHOD:REPLY
PARTSTAT:TENTATIVE
```

## Key Fields to Preserve

- **UID**: Must match the original invite exactly
- **SEQUENCE**: Increment by 1 from the original
- **DTSTAMP**: Current timestamp in UTC
- **ORGANIZER**: Copy from original
- **ATTENDEE**: Your email with updated PARTSTAT

## Threading

Always include threading headers so the reply links to the original invite:

- `in_reply_to`: Original email's `message_id`
- `references`: Original `references_chain` + `message_id`

## Notes

- The API extracts calendar content automatically (see commit `5c3fbf3`)
- If the HTML body is empty, the server uses the calendar content as the main HTML
- The reply is sent as a regular email with the VCALENDAR as the body content
- Some calendar systems (Outlook, Google) will automatically update the meeting status when they receive the reply

## Example: Full Accept Flow

```python
#!/usr/bin/env python3
"""Accept a meeting invite by email ID."""

import re
import sys
from datetime import datetime, timezone
from skills.local-email.scripts.mail_api import MailAPI

def accept_invite(email_id: int, comment: str = "I accept the meeting invitation."):
    api = MailAPI()
    
    # Get the invite
    invite = api.get_email(email_id)
    if not invite:
        print(f"Email {email_id} not found")
        return False
    
    # Extract calendar
    cal_content = invite.get('calendar')
    if not cal_content:
        print("No calendar content found in this email")
        return False
    
    # Parse VCALENDAR
    uid = re.search(r'UID:([^\r\n]+)', cal_content).group(1)
    sequence = int(re.search(r'SEQUENCE:(\d+)', cal_content).group(1))
    organizer = re.search(r'ORGANIZER[^:]*:mailto:([^\r\n]+)', cal_content).group(1)
    
    # Build acceptance
    dtstamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    accept_cal = f'''BEGIN:VCALENDAR
METHOD:REPLY
PRODID:Microsoft Exchange Server 2010
VERSION:2.0
BEGIN:VEVENT
UID:{uid}
SEQUENCE:{sequence + 1}
DTSTAMP:{dtstamp}
ORGANIZER:{organizer}
ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;CN={api.email_address}:mailto:{api.email_address}
SUMMARY;LANGUAGE=en-US:Accepted: {invite['subject']}
END:VEVENT
END:VCALENDAR'''
    
    # Send reply
    result = api.send_email(
        to=organizer,
        subject=f"Accepted: {invite['subject']}",
        body=comment,
        in_reply_to=invite['message_id'],
        references=f"{invite.get('references_chain', '')} {invite['message_id']}".strip(),
    )
    
    print(f"Acceptance sent: email_id={result.get('id')}")
    return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: accept_invite.py <email_id> [comment]")
        sys.exit(1)
    
    email_id = int(sys.argv[1])
    comment = sys.argv[2] if len(sys.argv) > 2 else "I accept the meeting invitation."
    accept_invite(email_id, comment)
```

## Related

- [RFC 5546](https://tools.ietf.org/html/rfc5546) — iCalendar Transport-Independent Interoperability Protocol (iTIP)
- [VCALENDAR Reply](https://docs.microsoft.com/en-us/exchange/client-developer/exchange-web-services/how-to-respond-to-a-meeting-request-by-using-ews-in-exchange)
