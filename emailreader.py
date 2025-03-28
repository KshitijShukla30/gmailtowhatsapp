from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from twilio.rest import Client
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import base64
import email
import os
import json
import time
import logging

# Load environment variables
load_dotenv()

# Gmail API setup
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
LAST_EMAIL_TIME_FILE = 'last_email_time.json'

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# Load last email timestamp
def load_last_email_time():
    if os.path.exists(LAST_EMAIL_TIME_FILE):
        with open(LAST_EMAIL_TIME_FILE, 'r') as file:
            return datetime.fromisoformat(json.load(file))
    return datetime.now(timezone.utc) - timedelta(minutes=5)

# Save last email timestamp
def save_last_email_time(last_time):
    with open(LAST_EMAIL_TIME_FILE, 'w') as file:
        json.dump(last_time.isoformat(), file)

def authenticate_gmail():
    creds = Credentials(
        token=os.getenv('GMAIL_TOKEN'),
        refresh_token=os.getenv('GMAIL_REFRESH_TOKEN'),
        client_id=os.getenv('GMAIL_CLIENT_ID'),
        client_secret=os.getenv('GMAIL_CLIENT_SECRET'),
        token_uri=os.getenv('GMAIL_TOKEN_URI')
    )

    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError:
            logging.error("⚠️ Token expired. Please update your '.env' file with a new token.")
            exit()

    return build('gmail', 'v1', credentials=creds, cache_discovery=False)

# Recursive function to extract email body
def extract_body(payload):
    if 'parts' in payload:
        for part in payload['parts']:
            if 'body' in part and 'data' in part['body']:
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
    return "No content available."

def get_latest_email(service):
    results = service.users().messages().list(
        userId='me',
        labelIds=['INBOX'],
        q='is:unread',
        maxResults=1
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        return None

    msg_details = service.users().messages().get(userId='me', id=messages[0]['id']).execute()
    headers = msg_details['payload']['headers']

    subject = next(header['value'] for header in headers if header['name'] == 'Subject')
    sender = next(header['value'] for header in headers if header['name'] == 'From')
    timestamp = datetime.fromtimestamp(int(msg_details['internalDate']) / 1000, tz=timezone.utc)

    body = extract_body(msg_details['payload'])

    return {'sender': sender, 'subject': subject, 'body': body, 'time': timestamp}

def send_whatsapp_message(message_body):
    account_sid = os.getenv('ACCOUNT_SID')
    auth_token = os.getenv('AUTH_TOKEN')
    from_number = os.getenv('WHATSAPP_NUMBER')
    to_number = os.getenv('TO_NUMBER')

    client = Client(account_sid, auth_token)

    try:
        message = client.messages.create(
            from_=from_number,
            body=message_body,
            to=to_number
        )
        logging.info(f"✅ WhatsApp Message Sent! SID: {message.sid}")
    except Exception as e:
        logging.error(f"❌ Failed to send WhatsApp message: {e}")

if __name__ == "__main__":
    last_email_time = load_last_email_time()

    while True:
        try:
            service = authenticate_gmail()  # Re-authenticate in every cycle
            latest_email = get_latest_email(service)

            if latest_email and latest_email['time'] > last_email_time:
                message_body = (
                    f"📧 From: {latest_email['sender']}\n"
                    f"📝 Subject: {latest_email['subject']}\n"
                    f"📄 Body: {latest_email['body'][:200]}..."
                )
                send_whatsapp_message(message_body)
                last_email_time = latest_email['time']
                save_last_email_time(last_email_time)
                logging.info("✅ New email detected and processed successfully.")
            else:
                logging.info("🔄 No new email detected. Checking again...")

        except Exception as e:
            logging.error(f"❗ An error occurred: {e}")

        time.sleep(1000)  # Check for new emails every ~5 seconds
