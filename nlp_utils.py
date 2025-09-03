import re
import spacy
from dateparser.search import search_dates
from dateparser import parse as parse_date
from datetime import datetime, timedelta

# Load spaCy model (ensure this is installed in your environment)
nlp = spacy.load("en_core_web_sm")

CONFIRM_WORDS = [r"\bconfirm\b", r"\byes\b", r"\byep\b", r"\bsure\b", r"\bok\b", r"\ball set\b", r"that's fine", r"that works", r"looks good"]
CANCEL_WORDS = [r"\bcancel\b", r"\bforget\b", r"\bno longer\b", r"\bnever mind\b"]
BOOK_WORDS = [r"\bbook\b", r"\breserve\b", r"\breservation\b", r"\bstay\b", r"\bbooking\b"]
GREET_WORDS = [r"^hi\b", r"^hello\b", r"^hey\b", r"good (morning|afternoon|evening)"]

WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"
}


def _match_any_word(list_patterns, text):
    if not text:
        return False
    t = text.lower()
    for pat in list_patterns:
        if re.search(pat, t):
            return True
    return False


def detect_intent(text):
    if not text or not text.strip():
        return "unknown"
    if _match_any_word(CONFIRM_WORDS, text):
        return "confirm"
    if _match_any_word(CANCEL_WORDS, text):
        return "cancel"
    if _match_any_word(BOOK_WORDS, text):
        return "book"
    if _match_any_word(GREET_WORDS, text):
        return "greet"
    t = text.lower()
    # heuristic: numbers + booking related words
    if re.search(r"\d", t) and ("night" in t or "guest" in t or "people" in t or "from" in t or "to" in t):
        return "book"
    return "unknown"


def _closest_year_for_month_day(dt, matched_text):
    # If user included a year explicitly, keep it.
    if re.search(r"\b(20\d{2})\b", matched_text):
        return dt
    today = datetime.now()
    candidates = []
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            cand = datetime(year=y, month=dt.month, day=dt.day, hour=dt.hour, minute=dt.minute, second=dt.second)
            candidates.append(cand)
        except ValueError:
            continue
    if not candidates:
        return dt
    closest = min(candidates, key=lambda c: abs((c - today).total_seconds()))
    return closest


def looks_like_name_response(text):
    """
    Heuristic to detect a likely name reply when user is asked for a name:
      - 1..3 alphabetic tokens (no digits)
      - rejects clear date-like / directive inputs (slashes, digits, words like 'from', 'next', etc.)
    This is intentionally permissive to accept common two-word names.
    """
    if not text or not text.strip():
        return False
    s = text.strip()
    # quick reject: contains digits or slashes (likely a date or structured input)
    if re.search(r"[0-9/\\\-:]", s):
        return False
    # alphabetic tokens only
    tokens = re.findall(r"[A-Za-z]+", s)
    if not (1 <= len(tokens) <= 3):
        return False
    low_tokens = [t.lower() for t in tokens]
    directives = {"from", "to", "next", "for", "night", "nights", "guest", "guests", "booking", "book", "checkin", "checkout", "payment", "breakfast"}
    if any(t in directives for t in low_tokens):
        return False
    return True


def extract_entities(text):
    """
    Parse a freeform user message and extract useful booking entities:
      - name
      - guests
      - breakfast (normalized values)
      - payment_method (normalized)
      - checkin, checkout, nights
    """
    if not text:
        return {}

    doc = nlp(text)
    extracted = {}

    # --- NAME via spaCy PERSON or phrasing like "I'm X" ---
    person_ents = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
    if person_ents:
        extracted["name"] = person_ents[0].strip()
    else:
        m = re.search(r"(?:i am|i'm|my name is|this is)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)", text)
        if m:
            extracted["name"] = m.group(1).strip()

    # --- GUESTS via CARDINAL or explicit phrase ---
    guests = None
    cardinals = [ent.text for ent in doc.ents if ent.label_ == "CARDINAL"]
    if cardinals:
        for c in cardinals:
            try:
                val = int(re.sub(r"[^\d]", "", c))
                guests = val
                break
            except Exception:
                continue
    if not guests:
        m = re.search(r"(\d+)\s*(?:guest|guests|person|people)", text, flags=re.I)
        if m:
            guests = int(m.group(1))
    extracted["guests"] = guests

    # --- BREAKFAST detection & normalization ---
    br = None
    if re.search(r"\bbreakfast\b", text, flags=re.I):
        m = re.search(r"breakfast[:\s-]*(yes|no|included|with|without|continental|American|buffet|full english|full|english|none)", text, flags=re.I)
        if m:
            br = m.group(1)
        else:
            # flexible keyword checks
            if re.search(r"(?:include|included|with)\s+breakfast", text, flags=re.I):
                br = "included"
            elif re.search(r"(?:no|without|none)\s+breakfast", text, flags=re.I):
                br = "no"
            else:
                if re.search(r"continental", text, flags=re.I):
                    br = "continental"
                elif re.search(r"buffet", text, flags=re.I):
                    br = "buffet"
                elif re.search(r"full\s+english|fullenglish|full english", text, flags=re.I):
                    br = "full english"
                else:
                    br = "unspecified"
    if br:
        br_norm = br.lower()
        if br_norm in ("yes", "with", "included", "include"):
            extracted["breakfast"] = "Included"
        elif br_norm in ("no", "none", "without"):
            extracted["breakfast"] = "No"
        elif "continental" in br_norm:
            extracted["breakfast"] = "Continental"
        elif "buffet" in br_norm:
            extracted["breakfast"] = "Buffet"
        elif "full" in br_norm or "english" in br_norm:
            extracted["breakfast"] = "Full English"
        else:
            # fallback: capitalize nicely
            extracted["breakfast"] = br.capitalize()

    # --- PAYMENT detection & normalization ---
    pay = None
    pay_m = re.search(r"\b(visa|mastercard|paypal|cash|card|debit|credit|american express|amex|crypto|bitcoin|btc)\b", text, flags=re.I)
    if pay_m:
        pay = pay_m.group(1)
    if re.search(r"\bpayment\b", text, flags=re.I) and not pay:
        m2 = re.search(r"payment[:\s-]*(visa|mastercard|paypal|cash|card|debit|credit|amex|american express|crypto|bitcoin|btc)", text, flags=re.I)
        if m2:
            pay = m2.group(1)
    if pay:
        pm = pay.lower()
        mapping = {
            "visa": "Visa", "mastercard": "Mastercard", "paypal": "PayPal", "cash": "Cash",
            "card": "Card", "debit": "Card", "credit": "Card", "american express": "Amex",
            "amex": "Amex", "crypto": "Crypto", "bitcoin": "Crypto", "btc": "Crypto"
        }
        extracted["payment_method"] = mapping.get(pm, pay.title())

    # --- DATES: skip date parsing if the whole message appears to be a name ---
    if looks_like_name_response(text) and not re.search(r"\b(i am|i'm|my name|name)\b", text, flags=re.I):
        # user probably gave a name — do not attempt to parse dates from this message
        return extracted

    # Use dateparser.search.search_dates to find date-like phrases
    dates = search_dates(text, settings={'PREFER_DATES_FROM': 'future'})
    normalized = []
    if dates:
        for matched_text, parsed_dt in dates:
            parsed_dt_norm = _closest_year_for_month_day(parsed_dt, matched_text)
            normalized.append((matched_text, parsed_dt_norm))

    if normalized:
        parsed_only = [d[1] for d in normalized]
        if len(parsed_only) >= 2:
            checkin = parsed_only[0]
            checkout = parsed_only[1]
            if checkout < checkin:
                checkin, checkout = checkout, checkin
            extracted["checkin"] = checkin
            extracted["checkout"] = checkout
            extracted["nights"] = max(1, (checkout.date() - checkin.date()).days)
        else:
            checkin = parsed_only[0]
            extracted["checkin"] = checkin
            # "for X nights"
            m = re.search(r"for\s+(\d+)\s+night", text, flags=re.I)
            if m:
                nights = int(m.group(1))
                extracted["nights"] = nights
                extracted["checkout"] = checkin + timedelta(days=nights)
            else:
                # Try to parse a trailing "to <date>" after the first date
                m2 = re.search(r"(?:to|until|through|-)\s*([A-Za-z0-9 ,\/\-]+)", text)
                if m2:
                    second_candidate = parse_date(m2.group(1), settings={'PREFER_DATES_FROM': 'future'})
                    if second_candidate:
                        second_candidate = _closest_year_for_month_day(second_candidate, m2.group(1))
                        # ensure reasonable ordering
                        if second_candidate < checkin:
                            second_candidate = _closest_year_for_month_day(second_candidate, m2.group(1))
                        extracted["checkout"] = second_candidate
                        extracted["nights"] = max(1, (second_candidate.date() - checkin.date()).days)

    # --- fallback: direct range like "Jan 12-15" ---
    range_m = re.search(
        r"([A-Za-z]{3,9}\s*\d{1,2}(?:,?\s*\d{4})?|\d{1,2}[\/\-]\d{1,2}(?:[\/\-]\d{2,4})?)\s*[-–]\s*"
        r"([A-Za-z]{3,9}\s*\d{1,2}(?:,?\s*\d{4})?|\d{1,2}[\/\-]\d{1,2}(?:[\/\-]\d{2,4})?)",
        text
    )
    if range_m and "checkin" not in extracted:
        d1 = parse_date(range_m.group(1))
        d2 = parse_date(range_m.group(2))
        if d1 and d2:
            if not re.search(r"\b(20\d{2})\b", range_m.group(1)):
                d1 = _closest_year_for_month_day(d1, range_m.group(1))
            if not re.search(r"\b(20\d{2})\b", range_m.group(2)):
                d2 = _closest_year_for_month_day(d2, range_m.group(2))
            if d2 < d1:
                d1, d2 = d2, d1
            extracted["checkin"] = d1
            extracted["checkout"] = d2
            extracted["nights"] = max(1, (d2.date() - d1.date()).days)

    return extracted
