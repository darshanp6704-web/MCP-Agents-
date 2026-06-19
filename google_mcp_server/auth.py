import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Define the scopes needed for Google Docs append and Gmail compose
SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/gmail.compose'
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')

def get_credentials():
    """
    Load or retrieve Google OAuth 2.0 credentials.
    Supports environment variables (GOOGLE_TOKEN_JSON and GOOGLE_CREDENTIALS_JSON)
    for headless deployment, falling back to local files.
    """
    import json
    creds = None
    
    # 1. Try loading cached token from environment variable (highest priority for cloud)
    env_token = os.environ.get("GOOGLE_TOKEN_JSON")
    if env_token:
        try:
            token_data = json.loads(env_token)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            print(f"Error loading GOOGLE_TOKEN_JSON from env: {e}")

    # 2. Fallback: Load credentials if token.json already exists locally
    if not creds and os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as e:
            print(f"Error loading token.json: {e}. Re-authenticating...")

    # If there are no valid credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save token back locally if env token wasn't used or we are local
                if not env_token:
                    try:
                        with open(TOKEN_PATH, 'w') as token_file:
                            token_file.write(creds.to_json())
                    except Exception as e:
                        print(f"Could not save refreshed token locally: {e}")
            except Exception as e:
                print(f"Error refreshing access token: {e}. Re-authenticating...")
                creds = None
        
        # If refreshing fails or token is missing, perform standard OAuth flow
        if not creds:
            # 3. Check for credentials in environment variable first
            env_creds = os.environ.get("GOOGLE_CREDENTIALS_JSON")
            if env_creds:
                try:
                    creds_data = json.loads(env_creds)
                    # We create flow from client configuration data directly
                    flow = InstalledAppFlow.from_client_config(creds_data, SCOPES)
                    # In a headless/cloud environment, we can't run a local server auth flow.
                    # We must assume the user has configured GOOGLE_TOKEN_JSON.
                    raise RuntimeError(
                        "Google credentials loaded from env, but access token is missing or expired. "
                        "Please run locally first to generate token.json, and set GOOGLE_TOKEN_JSON in your env variables."
                    )
                except Exception as e:
                    raise RuntimeError(f"Authentication setup error: {e}")

            # 4. Fallback: standard file-based flow
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"Google client credentials file not found at: {CREDENTIALS_PATH}. "
                    "Please download credentials.json from Google Cloud Console and place it in the same directory."
                )
            
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())
                
    return creds
