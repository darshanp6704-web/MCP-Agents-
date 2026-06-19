# Railway Deployment Plan for Google Workspace MCP Server

This document outlines the architecture adaptations and deployment steps required to run your Google Workspace MCP Server on **Railway**.

---

## 1. Cloud Architecture Challenges & Solutions

Deploying a local command-line interactive server to a cloud-native platform like Railway introduces three main challenges:

### Challenge A: Interactive Terminal Prompts
* **Problem**: The server currently stops and asks `Approve? (y/n)` using standard input (`sys.stdin`). Headless servers in the cloud do not have active terminal stdin. The server will raise an `EOFError` and reject all requests.
* **Solution**: Introduce a `BYPASS_APPROVAL` environment variable. When set to `true`, the server automatically executes the integrations without console verification.

### Challenge B: Dynamic Port Assignment
* **Problem**: Railway dynamically assigns a port to the web service via the `PORT` environment variable. The server must bind to `0.0.0.0` and use this dynamic port.
* **Solution**: Update `server.py` to read `os.environ.get("PORT", 8000)` and bind to host `0.0.0.0`.

### Challenge C: Secret File Configuration (`credentials.json` & `token.json`)
* **Problem**: Storing credentials and tokens directly in GitHub commits is a security vulnerability.
* **Solution**: Update `auth.py` to read these secrets directly from Railway Environment Variables (`GOOGLE_CREDENTIALS_JSON` and `GOOGLE_TOKEN_JSON`) in stringified JSON format.

---

## 2. Required Code Modifications

To support Railway deployment, we will apply these non-breaking modifications to the existing server code:

### Edit 1: [auth.py](file:///Users/darshan/Desktop/Build%20Projects/MCP%20Server/google-mcp-server/auth.py)
Update credential loading logic to look for environment variables before falling back to local files.

```python
import json
# ...
def get_credentials():
    creds = None
    # 1. Check for cached token in environment
    env_token = os.environ.get("GOOGLE_TOKEN_JSON")
    if env_token:
        try:
            token_data = json.loads(env_token)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            print(f"Error loading GOOGLE_TOKEN_JSON from env: {e}")

    # 2. Fallback to local token.json file
    if not creds and os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as e:
            print(f"Error loading token.json: {e}")
```

### Edit 2: [server.py](file:///Users/darshan/Desktop/Build%20Projects/MCP%20Server/google-mcp-server/server.py)
Integrate environment bypass checks and dynport resolution.

```python
import os
# ...
def ask_approval(action_name: str, payload: dict) -> bool:
    if os.environ.get("BYPASS_APPROVAL", "").lower() == "true":
        print(f"[AUTO-APPROVED] Action: {action_name}")
        return True
    # (Terminal input logic...)
# ...
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
```

---

## 3. Step-by-Step Railway Deployment

### Step 1: Prep Code
Ensure your files are committed to a GitHub repository (excluding `credentials.json` and `token.json`).

### Step 2: Create Railway Project
1. Log in to [Railway.app](https://railway.app/).
2. Click **New Project** and select **Deploy from GitHub repo**.
3. Choose your repository containing `google-mcp-server`.

### Step 3: Configure Environment Variables
In the **Variables** tab of your Railway service, add the following key-values:

| Variable Name | Value Description | Example Value |
| :--- | :--- | :--- |
| `PORT` | Auto-assigned by Railway | *(Do not set manually)* |
| `BYPASS_APPROVAL` | Skips command-line terminal confirmations | `true` |
| `GOOGLE_CREDENTIALS_JSON` | Content of your local `credentials.json` as a single-line string | `{"installed":{"client_id":"...","project_id":"..."}}` |
| `GOOGLE_TOKEN_JSON` | Content of your generated `token.json` as a single-line string | `{"token":"...","refresh_token":"..."}` |

### Step 4: Run Command Config
Go to **Settings > Deploy > Start Command** on Railway and configure it to run:
```bash
uvicorn google-mcp-server.server:app --host 0.0.0.0 --port $PORT
```
*(Since `requirements.txt` is now at the repository root, Railpack will build it automatically, and the above command imports the app module via path).*
