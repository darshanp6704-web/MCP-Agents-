from googleapiclient.discovery import build
from auth import get_credentials

def append_to_doc(doc_id: str, content: str) -> dict:
    """
    Appends text content to the end of a Google Document.
    """
    creds = get_credentials()
    service = build('docs', 'v1', credentials=creds)
    
    # Retrieve the document to find the endIndex of the last element
    doc = service.documents().get(documentId=doc_id).execute()
    
    body_content = doc.get('body', {}).get('content', [])
    if not body_content:
        raise ValueError("The document body is empty or invalid.")
    
    # The endIndex of the last body structural element
    end_index = body_content[-1].get('endIndex')
    
    # Google Docs requires character offset of >= 1 for insertions.
    # To append to the very end, we use the endIndex of the last element,
    # minus 1 to place it before the final segment boundary.
    insert_index = max(1, end_index - 1)
    
    requests = [
        {
            'insertText': {
                'location': {
                    'index': insert_index,
                },
                'text': content
            }
        }
    ]
    
    result = service.documents().batchUpdate(
        documentId=doc_id,
        body={'requests': requests}
    ).execute()
    
    return result
