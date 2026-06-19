import re

# Email pattern
EMAIL_REGEX = re.compile(r'\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b')

# Indian mobile numbers and generic 10-digit phone patterns
# Matches formats like +91 9999999999, 919999999999, 99999-99999, 09999999999, etc.
PHONE_REGEX = re.compile(
    r'\+91[\-\s]?[6-9]\d{9}\b|'             # matches +91 9876543210 or +919876543210
    r'\b91[6-9]\d{9}\b|'                    # matches 919876543210
    r'\b[6-9]\d{9}\b|'                      # matches 9876543210 (starts with 6-9)
    r'\b\d{10}\b|'                          # matches general 10 digits
    r'\b\d{5}[\-\s]\d{5}\b'                 # matches 98765-43210
)

# Identity numbers: PAN cards, Aadhaar cards, and credit cards (12-16 digit numbers)
PAN_REGEX = re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', re.IGNORECASE)
AADHAAR_REGEX = re.compile(r'\b\d{4}[\-\s]?\d{4}[\-\s]?\d{4}\b')
GENERIC_ID_REGEX = re.compile(r'\b\d{12,16}\b')

# URLs pattern
URL_REGEX = re.compile(r'https?://[^\s]+')

def scrub_pii(text: str) -> str:
    """
    Redacts PII from the input string based on the following pattern classes:
    - Email -> [EMAIL]
    - Phone -> [PHONE]
    - PAN / Aadhaar / 12-16 digit IDs -> [ID]
    - URLs -> [URL]
    
    Keeps financial references (like 10k, lakhs, INR, $...) as they represent useful theme signals.
    """
    if not text:
        return ""

    # Redact email addresses
    text = EMAIL_REGEX.sub("[EMAIL]", text)

    # Redact phone numbers (avoiding redacting financial numbers like 1000000000 by checking context if needed,
    # but standard Indian mobile number prefix check + 10-digit validation covers phone numbers).
    text = PHONE_REGEX.sub("[PHONE]", text)

    # Redact PAN and Aadhaar/numeric IDs
    text = PAN_REGEX.sub("[ID]", text)
    text = AADHAAR_REGEX.sub("[ID]", text)
    text = GENERIC_ID_REGEX.sub("[ID]", text)

    # Redact URLs
    text = URL_REGEX.sub("[URL]", text)

    # Collapse multiple consecutive redact tags (e.g. [ID] [ID])
    text = re.sub(r'(\[EMAIL\]\s*)+', '[EMAIL] ', text)
    text = re.sub(r'(\[PHONE\]\s*)+', '[PHONE] ', text)
    text = re.sub(r'(\[ID\]\s*)+', '[ID] ', text)
    text = re.sub(r'(\[URL\]\s*)+', '[URL] ', text)

    return " ".join(text.split()).strip()
