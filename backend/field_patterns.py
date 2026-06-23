"""Per-field content scorers + small value vocabularies learned from the CRM.

These power the CRM-INDEPENDENT extractor: each field is given a function that
scores how well a window of OCR tokens looks like that field's value (by regex
shape and/or a vocabulary learned in aggregate from the export - never a
per-record lookup). The order-preserving segmenter in image_to_excel.py uses
these scores to slice each form's token stream into the fixed field order, so a
brand-new record number is handled like any other.

Nothing here forces the output to a known value: vocabularies are used only to
RECOGNISE a field, the raw OCR text is what gets written.
"""

import json
import os
import re

from rapidfuzz import fuzz

from fields import FIELDS

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CRM = os.path.join(HERE, "data", "all_user_forms_details 2.json")

# Fields the form actually prints, in order, excluding the derived Total Amount.
LOCATABLE = [k for k, _, _, on_form in FIELDS if on_form and k != "total_amount"]

# --- shape regexes -------------------------------------------------------------
DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
ZIP = re.compile(r"^\d{5}(-\d{2,4})?$")
PHONE = re.compile(r"^\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}$")
MONEY = re.compile(r"^\d{2,6}[\$4]$")  # $ is often OCR'd as a trailing 4
POLICY = re.compile(r"^[Pp][-\s]?\d{6,}$")
CARD = re.compile(r"^[Cc][-\s]?\d{6,}$")
CODE16 = re.compile(r"^[A-Za-z0-9]{13,18}$")
CODE_SHORT = re.compile(r"^[A-Za-z0-9]{5,9}$")
BLOOD = re.compile(r"^(AB|A|B|O|0)\s?[+\-]$")
BLOOD_LETTERS = {"A", "B", "AB", "O", "0"}
# Characters OCR commonly produces in place of the +/- sign after a blood group:
# '+' gets read as t/T/4 (or split into its own token), '-' as a dash/underscore.
_BLOOD_PLUS_LIKE = set("+T4")
_BLOOD_MINUS_LIKE = set("-—–~_")
_BLOOD_SIGN_LIKE = _BLOOD_PLUS_LIKE | _BLOOD_MINUS_LIKE

# US state / territory 2-letter codes — used only as a guidance anchor so a clean
# state reading locks hard during segmentation. Unknown 2-letter codes still pass
# (see _s_state) so non-US / unseen states are handled too.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI", "AS", "MP",
}
ALPHA_WORD = re.compile(r"^[A-Za-z][A-Za-z.'\-]*$")
HAS_DIGIT = re.compile(r"\d")
STREET_KW = {
    "ST", "ST.", "STREET", "AVE", "AVE.", "AVENUE", "RD", "RD.", "ROAD", "BLVD",
    "DR", "DR.", "DRIVE", "LN", "LANE", "CT", "PL", "PL.", "WAY", "APT", "APT.",
    "BOX", "PO", "P.O.", "SUITE", "STE", "FLOOR", "HWY", "PKWY", "SQ", "TER",
    "CIR", "PLAZA", "N", "S", "E", "W", "NW", "NE", "SW", "SE",
}

# --- vocabularies learned from the export (aggregate, not per-record) ----------
_VOCAB = None


def _load_vocab():
    global _VOCAB
    if _VOCAB is not None:
        return _VOCAB
    from image_to_excel import normalize_record  # local import avoids a cycle

    vocab = {k: set() for k in LOCATABLE}
    try:
        with open(DEFAULT_CRM, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        raw = []
    for rec in raw:
        r = normalize_record(rec)
        for k in LOCATABLE:
            v = str(r.get(k, "")).strip().upper()
            if v:
                vocab[k].add(v)
    _VOCAB = vocab
    return vocab


def _vocab(key):
    return _load_vocab().get(key, set())


def _best_vocab_score(value, key):
    vocab = _vocab(key)
    if not vocab:
        return 0.0
    up = value.upper()
    if up in vocab:
        return 100.0
    # cheap fuzzy: only compare to entries of similar length
    best = 0.0
    for cand in vocab:
        if abs(len(cand) - len(up)) <= 3:
            best = max(best, fuzz.ratio(up, cand))
    return best


# --- per-field scorers (each returns 0..100 for a window of tokens) ------------
def _alpha_ratio(tokens):
    if not tokens:
        return 0.0
    return sum(bool(ALPHA_WORD.match(t)) for t in tokens) / len(tokens)


def _s_name(tokens):
    return 40 + 25 * _alpha_ratio(tokens)


def _s_city(tokens):
    if not tokens:
        return 0.0
    up = [t.upper().strip(",.") for t in tokens]
    if up[0] in STREET_KW:  # cities don't start with St/Ct/NE/Ave...
        return 16.0
    if any(HAS_DIGIT.search(t) for t in tokens):  # nor contain house/route numbers
        return 16.0
    return 42 + 20 * _alpha_ratio(tokens)


ADDR_START_KW = {"PO", "P.O.", "P.O", "BOX", "POBOX", "P.O.BOX", "STE", "SUITE",
                 "APT", "UNIT", "ATTN"}


def _s_address(tokens):
    if not tokens:
        return 0.0
    up = [t.upper().strip(",.") for t in tokens]
    score = 40.0
    # An address starts like one if it begins with a house number OR a PO-box /
    # suite keyword (so "P.O. Box 82533" reads as the address, not bleeding its
    # "P.O. Box" prefix back into the agent_name before it).
    if HAS_DIGIT.search(tokens[0]) or up[0] in ADDR_START_KW:
        score += 28
    if any(t in STREET_KW for t in up):
        score += 22
    score += 6 * sum(bool(HAS_DIGIT.search(t)) for t in tokens) / len(tokens)
    if up[-1] in STREET_KW:  # a street suffix is a strong "address ends here" cue
        score += 6
    return min(score, 96)


def _s_state(tokens):
    # A strong anchor: a real 2-letter state locks hard so the city before it is
    # not split. Anything else scores very low so it can't masquerade as a state.
    if len(tokens) != 1:
        return 3.0
    # Strip leading non-alpha junk (e.g. OCR '<' artifact before 'NY')
    cleaned = re.sub(r'^[^A-Za-z]+', '', tokens[0]).upper().strip(".,")
    # A known US state code, or a value learned from the CRM export, is a hard
    # anchor so the city before it is not split.
    if (cleaned in US_STATES
            or cleaned in _vocab("agent_state")
            or cleaned in _vocab("ph_state")
            or cleaned in _vocab("nominee_state")):
        return 100.0
    # Any other clean 2-letter alpha code still passes (handles non-US / unseen
    # states); reject long words like city names.
    return 80.0 if re.fullmatch(r"[A-Za-z]{2}", cleaned) else 3.0


def _s_zip(tokens):
    return 95.0 if ZIP.match("".join(tokens)) else 8.0


def _s_phone(tokens):
    return 95.0 if PHONE.match("".join(tokens)) else 10.0


def _s_date(tokens):
    return 92.0 if len(tokens) == 1 and DATE.match(tokens[0]) else 8.0


def _s_email(tokens):
    v = "".join(tokens).upper()
    return 95.0 if "@" in v and ("TEST" in v or "MAIL" in v) else 8.0


def _s_na(tokens):
    v = "".join(tokens).upper().replace(",", ".")
    return 88.0 if v in {"NA", "NA.", "N.A", "N.A."} or v.startswith("N.A") else 15.0


def _s_money(tokens):
    return 90.0 if len(tokens) == 1 and MONEY.match(tokens[0]) else 8.0


def _s_blood(tokens):
    # One of a tiny fixed set (A/B/AB/O with +/-). Never spans more than the
    # group itself, so it can't swallow the Policy No "P-..." that follows.
    if not tokens or len(tokens) > 2:
        return 4.0
    joined = "".join(tokens).upper().replace(" ", "").replace("0", "O")
    if BLOOD.match(joined):  # full group, sign possibly split into its own token
        return 98.0
    # Letter + a 1-char sign that OCR mangled (e.g. '+' -> 't'/'4', '-' -> '—').
    # Claim it so the sign is kept instead of dropped or leaked into policy_no.
    if len(tokens) == 2:
        letter = tokens[0].upper().replace("0", "O")
        sign = tokens[1].upper()
        if letter in BLOOD_LETTERS and len(sign) == 1 and sign in _BLOOD_SIGN_LIKE:
            return 92.0
    if len(tokens) == 1 and joined.rstrip("+-") in BLOOD_LETTERS:  # sign lost by OCR
        return 75.0
    return 5.0


def _s_policy(tokens):
    # OCR frequently splits "P-649337582299351" into "P-" + "649337582299351";
    # joining up to two tokens lets the policy number be captured whole instead
    # of leaking its digits into the following reference_no column.
    if not tokens or len(tokens) > 2:
        return 6.0
    joined = "".join(tokens).upper().replace(" ", "")
    if POLICY.match(joined):
        return 95.0
    # OCR sometimes drops the leading "P", leaving a bare 14-16 digit run. At the
    # policy position that is the policy number (canonicalize re-adds the "P-"),
    # so claim it here instead of letting it strand in the blood_group column.
    if re.fullmatch(r"\d{14,16}", joined):
        return 90.0
    return 6.0


def _s_card_no(tokens):
    return 95.0 if CARD.match("".join(tokens)) else 6.0


def _s_code16(tokens):
    if len(tokens) != 1 or not CODE16.match(tokens[0]):
        return 18.0
    t = tokens[0]
    # Real reference/agent/transaction codes are mixed alphanumerics. An all-digit
    # (or all-alpha) run is almost always a policy/card number that OCR split off,
    # so score it low here to stop it being stolen from policy_no/card_no.
    if any(c.isalpha() for c in t) and any(c.isdigit() for c in t):
        return 88.0
    return 25.0


def _s_record(tokens):
    v = "".join(tokens).upper()
    return 100.0 if len(tokens) == 1 and "@" in v and re.search(r"@\D{0,2}\d{3,6}", v) and "LIFEINS" not in v else 5.0


def _s_invoice(tokens):
    v = "".join(tokens).upper()
    return 98.0 if "LIFEINS" in v or "MAX@" in v else 6.0


def _s_customer(tokens):
    if len(tokens) != 1:
        return 10.0
    t = tokens[0]
    return 65.0 if CODE_SHORT.match(t) and "@" not in t and not DATE.match(t) else 20.0


def _s_file(tokens):
    if len(tokens) != 1:
        return 10.0
    return 60.0 if re.fullmatch(r"[A-Za-z0-9]{8,12}", tokens[0]) else 18.0


def _s_plan_code(tokens):
    if len(tokens) != 1:
        return 8.0
    return 65.0 if re.fullmatch(r"[A-Za-z0-9]{6,8}", tokens[0]) else 18.0


def _s_int(lo, hi):
    def f(tokens):
        if len(tokens) != 1 or not tokens[0].isdigit():
            return 8.0
        return 88.0 if lo <= int(tokens[0]) <= hi else 30.0
    return f


def _s_plan_name(tokens):
    v = " ".join(tokens).upper()
    return 95.0 if "PLAN" in v else 8.0


def _s_period(tokens):
    v = " ".join(tokens).upper()
    return 93.0 if "YEAR" in v else 8.0


def _s_yesno(tokens):
    if len(tokens) != 1:
        return 6.0
    up = tokens[0].upper().strip(".,")
    return 95.0 if up in {"NO", "YES", "N.A", "NA"} else 6.0


def _s_payment(tokens):
    v = " ".join(tokens).upper()
    return 90.0 if "CREDIT" in v or "CASH" in v else 12.0


def _s_card_type(tokens):
    sc = _best_vocab_score(" ".join(tokens), "card_type")
    return max(sc, 20.0 * _alpha_ratio(tokens))


def _s_agent_name(tokens):
    sc = _best_vocab_score(" ".join(tokens), "agent_name")
    base = max(sc * 0.95, 42 + 18 * _alpha_ratio(tokens))
    # Agent/company names never contain house or route numbers, so a window that
    # swallows a digit token is really reaching into agent_address; penalise it.
    digit_tokens = sum(bool(HAS_DIGIT.search(t)) for t in tokens)
    base -= 30 * digit_tokens
    # Nor do they end in a street/PO-box keyword ("...Company P.O. Box"); peel
    # those trailing tokens back so they land in agent_address instead.
    up = [t.upper().strip(".,") for t in tokens]
    trailing = 0
    for t in reversed(up):
        if t in STREET_KW or t in ADDR_START_KW:
            trailing += 1
        else:
            break
    return base - 20 * trailing


# key -> (min_len, max_len, ideal_len, scorer)
SPEC = {
    "record_no": (1, 1, 1, _s_record),
    "invoice_no": (1, 2, 1, _s_invoice),
    "date_of_purchase": (1, 1, 1, _s_date),
    "customer_id": (1, 1, 1, _s_customer),
    "file_no": (1, 1, 1, _s_file),
    "ph_name": (1, 4, 2, _s_name),
    "ph_address": (1, 7, 3, _s_address),
    "ph_city": (1, 3, 2, _s_city),
    "ph_state": (1, 1, 1, _s_state),
    "ph_zip": (1, 2, 1, _s_zip),
    "ph_phone": (1, 2, 2, _s_phone),
    "ph_email": (1, 1, 1, _s_email),
    "ph_dob": (1, 1, 1, _s_date),
    "education": (1, 1, 1, _s_na),
    "nominee_name": (1, 4, 2, _s_name),
    "nominee_address": (1, 7, 3, _s_address),
    "nominee_city": (1, 3, 2, _s_city),
    "nominee_state": (1, 1, 1, _s_state),
    "nominee_zip": (1, 2, 1, _s_zip),
    "relation_with_nominee": (1, 1, 1, _s_na),
    "chest": (1, 1, 1, _s_int(60, 99)),
    "height": (1, 1, 1, _s_int(140, 210)),
    "weight": (1, 1, 1, _s_int(80, 220)),
    "blood_group": (1, 2, 1, _s_blood),
    "policy_no": (1, 2, 1, _s_policy),
    "reference_no": (1, 1, 1, _s_code16),
    "agent_name": (1, 12, 3, _s_agent_name),
    "agent_address": (1, 8, 3, _s_address),
    "agent_city": (1, 3, 1, _s_city),
    "agent_state": (1, 2, 1, _s_state),
    "agent_zip": (1, 1, 1, _s_zip),
    "agent_code": (1, 1, 1, _s_code16),
    "agent_licence_no": (1, 1, 1, _s_code16),
    "plan_name": (1, 2, 2, _s_plan_name),
    "plan_code": (1, 1, 1, _s_plan_code),
    "sum_of_insured": (1, 1, 1, _s_money),
    "period_of_insurance": (1, 2, 2, _s_period),
    "q1_alcohol": (1, 1, 1, _s_yesno),
    "q2_medication": (1, 1, 1, _s_yesno),
    "q3a_hypertension": (1, 1, 1, _s_yesno),
    "q3b_diabetes": (1, 1, 1, _s_yesno),
    "q3c_cardiovascular": (1, 1, 1, _s_yesno),
    "q3d_genitourinary": (1, 1, 1, _s_yesno),
    "q4_hiv": (1, 1, 1, _s_yesno),
    "q5_other_insurance": (1, 1, 1, _s_yesno),
    "q6_involved_pursue": (1, 1, 1, _s_yesno),
    "q7_glasses": (1, 1, 1, _s_yesno),
    "payment_option": (1, 2, 2, _s_payment),
    "premium": (1, 1, 1, _s_money),
    "discount": (1, 1, 1, _s_money),
    "card_type": (1, 2, 1, _s_card_type),
    "card_no": (1, 1, 1, _s_card_no),
    "expiry_date": (1, 1, 1, _s_na),
    "card_holder_name": (1, 4, 2, _s_name),
    "transaction_id": (1, 1, 1, _s_code16),
}


# --- output canonicalisation --------------------------------------------------
# Small, stable enumerations: snap a noisy OCR reading to the nearest known value
# (helps with /-vs- and accent/glyph noise). New values still pass through when
# nothing matches closely enough.
CANON_ENUM = {
    "payment_option": ["Credit Card", "Cash/Credit Card"],
    "card_type": ["Visa", "American Express", "MasterCard", "Discover",
                  "Diners Club", "JCB", "Voyager", "enRoute"],
    "plan_name": [f"PLAN {c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
    "blood_group": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
    "education": ["N.A."],
    "expiry_date": ["N.A."],
    "relation_with_nominee": ["N.A."],
}
MONEY_FIELDS = {"sum_of_insured", "premium", "discount"}
PERIOD_FIELDS = {"period_of_insurance"}
PREFIX_FIELDS = {"policy_no": "P", "card_no": "C"}


def _canon_blood(value):
    """Recover the blood group +/- sign when OCR garbled or split it.

    The letter is always one of A/B/AB/O; anything trailing it is the sign, which
    OCR may render as a look-alike (t/4 for '+', a dash/underscore for '-') or as
    a separate token. If no sign is present at all we keep just the letter (we
    can't invent it); extract_row flags that case in the Remark column.
    """
    s = re.sub(r"\s+", "", value).upper().replace("0", "O")
    m = re.match(r"^(AB|A|B|O)(.*)$", s)
    if not m:
        return value
    letter, rest = m.group(1), m.group(2)
    if any(c in _BLOOD_PLUS_LIKE for c in rest):
        return letter + "+"
    if any(c in _BLOOD_MINUS_LIKE for c in rest):
        return letter + "-"
    return letter


def canonicalize(key, value):
    """Normalise a raw OCR value to the field's canonical form/format."""
    if not value:
        return value
    v = value.strip()
    if "?" in v:
        return v
    if key == "blood_group":
        return _canon_blood(v)
    if key in CANON_ENUM:
        opts = CANON_ENUM[key]
        best = max(opts, key=lambda o: fuzz.ratio(v.upper(), o.upper()))
        return best if fuzz.ratio(v.upper(), best.upper()) >= 78 else v
    if key in MONEY_FIELDS:
        core = re.sub(r"[\$4]$", "", v)  # trailing $ (often OCR'd as 4) is the marker
        return core + "$" if core.isdigit() else v
    if key in PERIOD_FIELDS:
        m = re.search(r"\d+", v)
        return f"{m.group(0)} Year" if m else v
    if key == "invoice_no":
        v = re.sub(r'^[L_I]*@\d{4,6}\s*', '', v, flags=re.IGNORECASE)
        return v
    if key in ("ph_state", "nominee_state", "agent_state"):
        # Strip leading non-alpha OCR junk (e.g. '<NY' -> 'NY')
        cleaned = re.sub(r'^[^A-Za-z]+', '', v).strip()
        # If the result is a clean 2-letter code, return it; otherwise keep original
        return cleaned if re.fullmatch(r'[A-Za-z]{2}', cleaned) else v
    if key in PREFIX_FIELDS:
        digits = re.sub(r"\D", "", v)
        return f"{PREFIX_FIELDS[key]}-{digits}" if len(digits) >= 6 else v
    return v


def field_score(key, tokens):
    """Content score (0..100) for assigning `tokens` to `key`, with a soft
    penalty for windows whose length is far from the field's typical length."""
    lo, hi, ideal, scorer = SPEC[key]
    base = scorer(tokens)
    n = len(tokens)
    if n < lo or n > hi:
        base -= 9 * (lo - n if n < lo else n - hi)
    base -= 1.5 * abs(n - ideal)
    return base
