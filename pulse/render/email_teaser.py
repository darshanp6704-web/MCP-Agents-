from datetime import datetime
from typing import List, Dict, Any, Tuple

def render_email_teaser(
    product_display_name: str,
    iso_week: str,
    doc_url: str,
    themes: List[Dict[str, Any]],
    window_weeks: int
) -> Tuple[str, str, str]:
    """
    Renders the Subject, HTML Body, and Plain Text Body for the email teaser.
    Contains bullet themes and a deep-link CTA pointing to the Google Doc section.
    """
    subject = f"{product_display_name} Weekly Review Pulse — {iso_week}"

    # Build top-level bullet themes
    bullet_items = []
    text_bullet_items = []
    
    # Cap themes list at top 5 for email brevity
    for theme in themes[:5]:
        name = theme.get("theme_name", "Unknown Theme")
        summary = theme.get("summary", "")
        bullet_items.append(f"<li><strong>{name}</strong>: {summary}</li>")
        text_bullet_items.append(f"- {name}: {summary}")
        
    html_bullets = "\n".join(bullet_items)
    text_bullets = "\n".join(text_bullet_items)
    
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    # 1. HTML Body
    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #333333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; }}
    h2 {{ color: #1e293b; font-size: 20px; margin-bottom: 10px; }}
    .cta {{ display: inline-block; background-color: #2563eb; color: #ffffff; text-decoration: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; margin-top: 15px; margin-bottom: 20px; }}
    .footer {{ font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 15px; margin-top: 25px; }}
    ul {{ padding-left: 20px; }}
    li {{ margin-bottom: 8px; }}
  </style>
</head>
<body>
  <h2>{product_display_name} Weekly Review Pulse ({iso_week})</h2>
  <p>Here is a summary of customer feedback compiled from Google Play Store reviews over the last {window_weeks} weeks:</p>
  
  <ul>
    {html_bullets}
  </ul>
  
  <p><a href="{doc_url}" class="cta">Read Full Report on Google Docs &rarr;</a></p>
  
  <div class="footer">
    <p>Generated: {timestamp} UTC | Source: Google Play Store<br>
    Document URL: <a href="{doc_url}">{doc_url}</a></p>
  </div>
</body>
</html>
"""

    # 2. Plain Text Body
    text_body = f"""{product_display_name} Weekly Review Pulse — {iso_week}

Here is a summary of customer feedback compiled from Google Play Store reviews over the last {window_weeks} weeks:

{text_bullets}

Read the full report, verbatim user quotes, and action items directly on Google Docs:
{doc_url}

---
Generated: {timestamp} UTC | Source: Google Play Store
"""

    return subject, html_body, text_body
