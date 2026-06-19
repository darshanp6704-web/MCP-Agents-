from googleapiclient.discovery import build
from email.message import EmailMessage
import base64
from auth import get_credentials

def create_email_draft(to: str, subject: str, body: str) -> dict:
    """
    Creates a Gmail draft email using the Gmail API.
    """
    creds = get_credentials()
    service = build('gmail', 'v1', credentials=creds)
    
    # Construct RFC 2822 email message
    message = EmailMessage()
    message.set_content(body)
    message['To'] = to
    message['Subject'] = subject
    
    # Encode message as base64url string
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    
    draft_body = {
        'message': {
            'raw': raw_message
        }
    }
    
    # Create draft
    draft = service.users().drafts().create(
        userId='me',
        body=draft_body
    ).execute()
    
    return draft
