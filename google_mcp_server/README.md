# Google Workspace MCP Server

An MCP-style server written in Python using FastAPI that integrates with Google Docs and Gmail.

## Features

1. **Google Docs Integration**: Post text content directly to the end of a specific Google Doc using its Document ID.
2. **Gmail Integration**: Create drafts with subject, body, and recipient fields.
3. **Manual Approval Prompt**: Intercepts actions before execution, printing details in the command line and prompting the administrator for explicit `(y/n)` approval.
4. **Cached OAuth 2.0**: Handles auth flow, caching the tokens locally in `token.json` after successful login to prevent repeated browser authentications.

---

## File Structure

```text
google_mcp_server/
├── server.py          → FastAPI app with tool endpoints
├── auth.py            → Google OAuth authentication helper
├── docs_tool.py       → Google Docs tool (append content)
├── gmail_tool.py      → Gmail tool (create draft)
├── requirements.txt   → Python dependencies list
├── README.md          → This setup and usage instructions guide
├── credentials.json   → (Not Committed) Downloaded from Google Cloud Console
└── token.json         → (Not Committed) Auto-generated after first OAuth login
```

---

## Step 1: Google Cloud Setup

To interact with Google Docs and Gmail, you must configure a project on Google Cloud Platform:

1. **Create a Project**:
   - Go to the [Google Cloud Console](https://console.cloud.google.com/).
   - Create a new project (e.g. `google-mcp-server`).

2. **Enable APIs**:
   - Navigate to **APIs & Services > Library**.
   - Search for and enable the following:
     * **Google Docs API**
     * **Gmail API**

3. **Configure OAuth Consent Screen**:
   - Go to **APIs & Services > OAuth consent screen**.
   - Select **External** (or Internal if using a Workspace Account).
   - Fill in developer contact details.
   - Under **Scopes**, click **Add or Remove Scopes**, then add:
     * `https://www.googleapis.com/auth/documents`
     * `https://www.googleapis.com/auth/gmail.compose`
   - Under **Test Users**, add the Google email account you plan to authorize with.

4. **Create OAuth Client Credentials**:
   - Go to **APIs & Services > Credentials**.
   - Click **Create Credentials > OAuth client ID**.
   - Set the Application Type to **Desktop app**.
   - Name the client (e.g., `Desktop Client`).
   - Click **Create**.
   - Download the client credentials JSON file, rename it to `credentials.json`, and place it in the `google_mcp_server/` directory.

---

## Step 2: Local Installation

1. Navigate to the project directory:
   ```bash
   cd google_mcp_server
   ```

2. (Optional but recommended) Set up a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Step 3: Run the Server

Start the FastAPI application with:
```bash
python server.py
```
Or with uvicorn directly:
```bash
uvicorn server:app --host 127.0.0.1 --port 8000
```

On first startup:
* The server will check for credentials and detect that `token.json` is missing.
* A browser tab will automatically open, asking you to authenticate with your test Google account.
* Click **Continue/Allow** to grant the app permission.
* Once completed, a `token.json` file is written to your directory, and the server will start handling HTTP requests. Future runs will use `token.json` directly.

---

## Step 4: Endpoint Usage

The server exposes two endpoints. Before each API executes, it will print the payload details in your terminal, waiting for you to type `y` (yes) or `n` (no).

### 1. Append to Document (`POST /append_to_doc`)

**Request:**
```bash
curl -X POST http://127.0.0.1:8000/append_to_doc \
     -H "Content-Type: application/json" \
     -d '{
       "doc_id": "YOUR_GOOGLE_DOC_ID",
       "content": "\nThis text was appended via the MCP tool!"
     }'
```

**Terminal Approval Prompt:**
```text
==================================================
APPROVAL REQUIRED
Action: Append to Google Doc
Payload: {'doc_id': 'YOUR_GOOGLE_DOC_ID', 'content': '\nThis text was appended via the MCP tool!'}
==================================================
Approve? (y/n): 
```

**Response:**
* **If approved (y)**:
  ```json
  {
    "status": "success",
    "detail": "Content appended successfully",
    "result": { ... }
  }
  ```
* **If rejected (n)**:
  ```json
  {
    "detail": "Action rejected by user in terminal."
  }
  ```

---

### 2. Create Email Draft (`POST /create_email_draft`)

**Request:**
```bash
curl -X POST http://127.0.0.1:8000/create_email_draft \
     -H "Content-Type: application/json" \
     -d '{
       "to": "recipient@example.com",
       "subject": "Greetings from MCP",
       "body": "Hello,\n\nThis is a draft email generated using the Gmail API integration server."
     }'
```

**Terminal Approval Prompt:**
```text
==================================================
APPROVAL REQUIRED
Action: Create Gmail Draft
Payload: {'to': 'recipient@example.com', 'subject': 'Greetings from MCP', 'body': 'Hello,\n\nThis is a draft email generated using the Gmail API integration server.'}
==================================================
Approve? (y/n): 
```

**Response:**
* **If approved (y)**:
  ```json
  {
    "status": "success",
    "detail": "Gmail draft created successfully",
    "result": { ... }
  }
  ```
* **If rejected (n)**:
  ```json
  {
     "detail": "Action rejected by user in terminal."
  }
  ```
