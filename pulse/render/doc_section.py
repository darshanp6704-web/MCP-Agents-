from datetime import datetime
from typing import List, Dict, Any

def render_doc_section_blocks(
    product_name: str,
    iso_week: str,
    window_weeks: int,
    themes: List[Dict[str, Any]],
    anchor_key: str
) -> List[Dict[str, str]]:
    """
    Renders structured blocks matching the Google Docs MCP server schema:
    [
      { "type": "heading1" | "heading2" | "paragraph" | "list_item", "text": "..." }
    ]
    """
    blocks = []
    
    # 1. Heading 1 (including the unique anchor key for idempotency)
    # The header title contains the anchor key to allow search lookup
    blocks.append({
        "type": "heading1",
        "text": f"{product_name} — Weekly Review Pulse — {iso_week} ({anchor_key})"
    })
    
    # 2. Metadata Paragraph
    timestamp_ist = datetime.utcnow().strftime("%Y-%m-%d %H:%M") # UTC for base logging
    blocks.append({
        "type": "paragraph",
        "text": f"Period: Last {window_weeks} weeks (rolling) · Source: Google Play Store · Generated: {timestamp_ist} UTC"
    })
    
    # 3. Top Themes
    blocks.append({
        "type": "heading2",
        "text": "Top Themes"
    })
    for theme in themes:
        theme_name = theme.get("theme_name", "Unknown Theme")
        summary = theme.get("summary", "")
        blocks.append({
            "type": "list_item",
            "text": f"{theme_name} — {summary}"
        })
        
    # 4. Real User Quotes
    blocks.append({
        "type": "heading2",
        "text": "Real User Quotes"
    })
    
    has_quotes = False
    for theme in themes:
        for quote in theme.get("quotes", []):
            if quote:
                blocks.append({
                    "type": "list_item",
                    "text": f'"{quote}"'
                })
                has_quotes = True
                
    if not has_quotes:
        blocks.append({
            "type": "paragraph",
            "text": "(No verified user quotes extracted for this period)"
        })
        
    # 5. Action Ideas
    blocks.append({
        "type": "heading2",
        "text": "Action Ideas"
    })
    
    has_actions = False
    for theme in themes:
        for action in theme.get("action_ideas", []):
            title = action.get("title", "")
            detail = action.get("detail", "")
            if title:
                blocks.append({
                    "type": "list_item",
                    "text": f"{title}: {detail}"
                })
                has_actions = True
                
    if not has_actions:
        blocks.append({
            "type": "paragraph",
            "text": "(No action ideas suggested)"
        })

    # 6. Who This Helps
    blocks.append({
        "type": "heading2",
        "text": "Who This Helps"
    })
    blocks.append({
        "type": "list_item",
        "text": "Product Managers: Focuses roadmap priorities on validated customer request categories."
    })
    blocks.append({
        "type": "list_item",
        "text": "Engineering: Pinpoints newly introduced crashing bugs or latency regressions."
    })
    blocks.append({
        "type": "list_item",
        "text": "Customer Support: Synthesizes core stakeholder issues to align review response flows."
    })

    return blocks
