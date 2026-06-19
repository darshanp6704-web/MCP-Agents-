import os
import sys

# Ensure python path includes this folder for child imports (important for running from root directory in cloud)
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from auth import get_credentials
from docs_tool import append_to_doc
from gmail_tool import create_email_draft

app = FastAPI(
    title="Google Workspace MCP Server",
    description="MCP-style server for appending content to Google Docs and creating Gmail drafts, with manual console approval.",
    version="1.0.0"
)

class AppendDocRequest(BaseModel):
    doc_id: str
    content: str

class CreateEmailDraftRequest(BaseModel):
    to: str
    subject: str
    body: str

def ask_approval(action_name: str, payload: dict) -> bool:
    """
    Prompts the user in the console to approve or reject the action.
    Bypasses if BYPASS_APPROVAL env variable is set to true.
    """
    import os
    if os.environ.get("BYPASS_APPROVAL", "").lower() == "true":
        print(f"\n[AUTO-APPROVED] Action: {action_name}")
        return True

    print(f"\n{'='*50}")
    print(f"APPROVAL REQUIRED")
    print(f"Action: {action_name}")
    print(f"Payload: {payload}")
    print(f"{'='*50}")
    while True:
        try:
            response = input("Approve? (y/n): ").strip().lower()
            if response == 'y':
                return True
            elif response == 'n':
                return False
            else:
                print("Invalid input. Please enter 'y' or 'n'.")
        except EOFError:
            print("Standard input EOF encountered. Action auto-rejected.")
            return False

@app.on_event("startup")
def startup_event():
    """
    Verify OAuth setup at startup.
    Triggers local login flow if no cached token is found.
    """
    print("\n[STARTUP] Checking Google Workspace API credentials...")
    try:
        get_credentials()
        print("[STARTUP] Authentication configuration is valid.\n")
    except FileNotFoundError as e:
        print("\n" + "!"*80)
        print("WARNING: credentials.json NOT FOUND!")
        print("The server will not be able to process actions until credentials.json is provided.")
        print("Please download credentials.json from Google Cloud Console and place it in this directory.")
        print("!"*80 + "\n")
    except Exception as e:
        print(f"\n[STARTUP] Authentication verification failed: {e}\n")

@app.post("/append_to_doc")
def append_to_doc_endpoint(payload: AppendDocRequest):
    """
    Endpoint to append content to a Google Doc.
    Requires manual console approval before proceeding.
    """
    data = {"doc_id": payload.doc_id, "content": payload.content}
    if not ask_approval("Append to Google Doc", data):
        raise HTTPException(status_code=403, detail="Action rejected by user in terminal.")
    
    try:
        result = append_to_doc(payload.doc_id, payload.content)
        return {"status": "success", "detail": "Content appended successfully", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to append to doc: {str(e)}")

@app.post("/create_email_draft")
def create_email_draft_endpoint(payload: CreateEmailDraftRequest):
    """
    Endpoint to create a draft email in Gmail.
    Requires manual console approval before proceeding.
    """
    data = {"to": payload.to, "subject": payload.subject, "body": payload.body}
    if not ask_approval("Create Gmail Draft", data):
        raise HTTPException(status_code=403, detail="Action rejected by user in terminal.")
    
    try:
        result = create_email_draft(payload.to, payload.subject, payload.body)
        return {"status": "success", "detail": "Gmail draft created successfully", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create draft: {str(e)}")

if __name__ == "__main__":
    import os
    # Bind to host 0.0.0.0 and dynamic port assigned by Railway, default to 8000
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host=host, port=port, reload=False)
