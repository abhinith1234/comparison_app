"""
extractor.py – Standalone form-field extractor.

The form template is FIXED: every printed value appears in the same order
as FIELD_ORDER.  We divide the OCR text into sections using STRONG ANCHORS
(email, policy_no prefix, card_no prefix, Yes/No block) and extract each
field within its section.

No CRM lookup.  No comparison.  No fallback substitution.
Whatever OCR read goes in; if OCR missed something the cell is blank.
"""

import re

from fields import FIELD_ORDER

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
    "NA",
}

_CARD_TYPES = [
    "Cash-Credit Card", "American Express", "MasterCard", "Visa",
    "Diners Club", "Credit Card",
]

_Q_KEYS = [
    "q1_alcohol", "q2_medication",
    "q3a_hypertension", "q3b_diabetes",
    "q3c_cardiovascular", "q3d_genitourinary",
    "q4_hiv", "q5_other_insurance",
    "q6_involved_pursue", "q7_glasses",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find(pattern, text, flags=re.IGNORECASE):
    m = re.search(pattern, text, flags)
    return m.group().strip() if m else ""


def _split_name_address_city(block):
    """
    Split a block containing 'Name Address City' into its components.
    """
    name = address = city = ""
    block = re.sub(r'\s+', ' ', block).strip()
    if not block:
        return name, address, city

    # 1. Check for N.A. or Not Applicable
    na_m = re.search(r'\bnot\s+applicable\b|\bn\.a\.(?!\w)|\bna\b', block, re.IGNORECASE)
    if na_m:
        addr_start = na_m.start()
        addr_end = na_m.end()
        name = block[:addr_start].strip()
        address = block[addr_start:addr_end].strip()
        city = block[addr_end:].strip()
        return name, address, city

    # 2. Check for PO Box patterns
    po_box_m = re.search(r'\b(?:p\.?\s*o\.?\s*)?box(?:\s+\w+)?\b', block, re.IGNORECASE)
    if po_box_m:
        addr_start = po_box_m.start()
        addr_end = po_box_m.end()
        pre_po = block[:addr_start].strip()
        
        pre_toks = pre_po.split()
        first_digit_i = None
        for i, t in enumerate(pre_toks):
            if any(c.isdigit() for c in t):
                first_digit_i = i
                break
        if first_digit_i is not None:
            name = " ".join(pre_toks[:first_digit_i]).strip()
            address = " ".join(pre_toks[first_digit_i:]).strip() + " " + block[addr_start:addr_end].strip()
        else:
            name = pre_po
            address = block[addr_start:addr_end].strip()
            
        city = block[addr_end:].strip()
        return name, address, city

    # Find first digit character index in block (if any)
    first_digit_char_idx = None
    digit_m = re.search(r'\d', block)
    if digit_m:
        first_digit_char_idx = digit_m.start()

    # 3. Check for street suffixes
    STREET_SUFFIXES_PAT = (
        r'\b(?:avenue\s+of\s+the\s+americas|street\s+dr|st\s+dr|'
        r'street|road|avenue|boulevard|drive|lane|court|place|plaza|highway|parkway|trail|broadway|'
        r'st|rd|ave|blvd|dr|ln|way|ct|pl|pi|hwy|pkwy|cir|circle|oval|loop|pte|vis|vista)(?:\.|\b)'
    )
    
    search_start = first_digit_char_idx if first_digit_char_idx is not None else 0
    suffix_m = re.search(STREET_SUFFIXES_PAT, block[search_start:], re.IGNORECASE)
    
    if suffix_m:
        suffix_start_in_block = search_start + suffix_m.start()
        addr_end = search_start + suffix_m.end()
        post_suffix = block[addr_end:]
        
        if suffix_m.group().lower() == 'broadway':
            next_word_m = re.match(
                r'^(?:[,\s?]+)?\b(st|st\.|street|rd|rd\.|road|ave|ave\.|avenue|blvd|blvd\.|boulevard|dr|dr\.|drive|ln|ln\.|lane|way|ct|ct\.|court|pl|pl\.|place|pi|plaza|hwy|highway|pkwy|parkway|trail|trail\.)\b',
                post_suffix, re.IGNORECASE
            )
            if next_word_m:
                addr_end += next_word_m.end()
                post_suffix = block[addr_end:]
        
        KNOWN_MULTIPLE_WORD_CITIES = {
            'south bend', 'south haven', 'south lake tahoe',
            'north bend', 'north brunswick', 'north hollywood', 'north bergen',
            'north haven', 'north highlands', 'north metro', 'north fort myers',
            'west berlin', 'west covina', 'west hollywood', 'west palm beach', 'west trenton',
            'east hartford', 'east orange', 'east berlin', 'east stroudsburg'
        }
        
        post_clean = post_suffix.strip().lower()
        is_multi_word_city = False
        for c in KNOWN_MULTIPLE_WORD_CITIES:
            if post_clean.startswith(c):
                is_multi_word_city = True
                break
                
        if not is_multi_word_city:
            dir_m = re.match(r'^(?:[,\s?]+)?\b(south|north|east|west|s|n|e|w|nw|ne|sw|se)\b', post_suffix, re.IGNORECASE)
            if dir_m:
                addr_end += dir_m.end()
                post_suffix = block[addr_end:]
            
        num_m = re.match(r'^(?:[,\s?]+)?\b\d+\b', post_suffix)
        if num_m:
            addr_end += num_m.end()
            post_suffix = block[addr_end:]

        floor_m = re.match(
            r'^(?:[,\s?]+)?\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|one|two|three|four|five|six|seven|eight|nine|ten|\d+(?:st|nd|rd|th)?)\s+(floor|fl|ste|apt|suite)\b',
            post_suffix, re.IGNORECASE
        )
        if floor_m:
            addr_end += floor_m.end()
            post_suffix = block[addr_end:]

        apt_m = re.match(r'^(?:[,\s?]+)?(?:\b(apt|suite|ste|unit|room|rm|lbl|floor|fl|ph|lot)\b\.?|#)\s*\w+', post_suffix, re.IGNORECASE)
        if apt_m:
            addr_end += apt_m.end()
            
        pre_suffix = block[:suffix_start_in_block].strip()
        toks = pre_suffix.split()
        
        first_digit_i = None
        for i, t in enumerate(toks):
            if any(c.isdigit() for c in t):
                first_digit_i = i
                break
                
        if first_digit_i is not None:
            name = " ".join(toks[:first_digit_i]).strip()
            address = " ".join(toks[first_digit_i:]).strip() + " " + block[suffix_start_in_block:addr_end].strip()
        else:
            DIR_PREFIXES = {
                'n', 's', 'e', 'w', 'n.', 's.', 'e.', 'w.',
                'north', 'south', 'east', 'west',
                'ne', 'nw', 'se', 'sw', 'ne.', 'nw.', 'se.', 'sw.',
                'northeast', 'northwest', 'southeast', 'southwest'
            }
            NUMBER_WORDS = {
                'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'
            }
            
            addr_start_tok_i = len(toks) - 1
            if len(toks) >= 2:
                prev_tok = toks[-2].lower().rstrip(',.')
                if prev_tok in DIR_PREFIXES or prev_tok in NUMBER_WORDS:
                    addr_start_tok_i = len(toks) - 2
                    
            name = " ".join(toks[:addr_start_tok_i]).strip()
            address = " ".join(toks[addr_start_tok_i:]).strip() + " " + block[suffix_start_in_block:addr_end].strip()
            
        address = address.strip()
        city = block[addr_end:].strip()
        city = re.sub(r'^[.,?\s]+', '', city).strip()
        return name, address, city

    # 3.5 Check for apartment/suite/unit markers (if no street suffix found)
    apt_only_m = re.search(r'(?:\b(apt|suite|ste|unit|room|rm|lbl|floor|fl|ph|lot)\b\.?|#)\s*\w+', block, re.IGNORECASE)
    if apt_only_m:
        addr_end = apt_only_m.end()
        pre_apt = block[:apt_only_m.start()].strip()
        pre_toks = pre_apt.split()
        
        first_digit_i = None
        for i, t in enumerate(pre_toks):
            if any(c.isdigit() for c in t):
                first_digit_i = i
                break
        if first_digit_i is not None:
            name = " ".join(pre_toks[:first_digit_i]).strip()
            address = " ".join(pre_toks[first_digit_i:]).strip() + " " + block[apt_only_m.start():addr_end].strip()
        else:
            name = pre_apt
            address = block[apt_only_m.start():addr_end].strip()
            
        city = block[addr_end:].strip()
        city = re.sub(r'^[.,?\s]+', '', city).strip()
        return name, address, city

    # 4. Check if the block ends with a repeated phrase (e.g. Columbia Columbia)
    toks = block.split()
    n_toks = len(toks)
    for l in range(n_toks // 2, 0, -1):
        phrase1 = toks[n_toks - 2*l : n_toks - l]
        phrase2 = toks[n_toks - l :]
        p1_clean = [t.lower().rstrip(',.') for t in phrase1]
        p2_clean = [t.lower().rstrip(',.') for t in phrase2]
        if p1_clean == p2_clean:
            name = " ".join(toks[:n_toks - 2*l]).strip()
            address = " ".join(phrase1).strip()
            city = " ".join(phrase2).strip()
            return name, address, city

    # 5. Check if last token matches an earlier token
    if len(toks) >= 3:
        last_tok_clean = toks[-1].lower().rstrip(',.')
        earlier_match_i = None
        for i in range(len(toks) - 1):
            if toks[i].lower().rstrip(',.') == last_tok_clean:
                earlier_match_i = i
                break
        if earlier_match_i is not None:
            name = " ".join(toks[:earlier_match_i]).strip()
            address = " ".join(toks[earlier_match_i:-1]).strip()
            city = toks[-1].strip()
            return name, address, city

    # 6. Smart address / city splitter when no street suffix is present
    first_digit_i = None
    for i, t in enumerate(toks):
        if any(c.isdigit() for c in t):
            first_digit_i = i
            break
            
    if first_digit_i is not None:
        name = " ".join(toks[:first_digit_i]).strip()
        addr_city_toks = toks[first_digit_i:]
        
        last_3_clean = " ".join(addr_city_toks[-3:]).lower().rstrip(',.')
        if last_3_clean in {'el dorado hills', 'new york city', 'salt lake city'}:
            address = " ".join(addr_city_toks[:-3]).strip()
            city = " ".join(addr_city_toks[-3:]).strip()
        else:
            CITY_SUFFIX_WORDS = {
                'city', 'county', 'country', 'valley', 'beach', 'park', 'springs', 'falls', 'grove', 'lake', 'hills',
                'angeles', 'diego', 'francisco', 'jose', 'antonio', 'bernardino', 'mateo', 'rafael', 'barbara',
                'clara', 'ana', 'monica', 'rosa', 'spring', 'cynwyd', 'rouge', 'trenton', 'orange', 'berlin',
                'covina', 'worth', 'lauderdale', 'myers', 'wayne', 'green', 'arrow', 'pass', 'breeze', 'plains',
                'land', 'york', 'rapids', 'moines', 'vista', 'mesa', 'paso', 'prairie', 'vegas', 'gatos', 'alto', 
                'pines', 'linda', 'heigh', 'chase', 'creek', 'orchard', 'twp', 'aire', 'river', 'harbor', 'sound', 
                'allen', 'station', 'heights', 'village', 'island'
            }
            if len(addr_city_toks) >= 3 and addr_city_toks[-1].lower().rstrip(',.') in CITY_SUFFIX_WORDS:
                address = " ".join(addr_city_toks[:-2]).strip()
                city = " ".join(addr_city_toks[-2:]).strip()
            elif len(addr_city_toks) >= 2:
                address = " ".join(addr_city_toks[:-1]).strip()
                city = addr_city_toks[-1].strip()
            else:
                address = ""
                city = addr_city_toks[0].strip()
        return name, address, city

    # 7. Default fallback
    if len(toks) >= 3:
        name = " ".join(toks[:-2]).strip()
        address = toks[-2].strip()
        city = toks[-1].strip()
    elif len(toks) == 2:
        name = toks[0].strip()
        address = toks[1].strip()
    else:
        name = block
        
    return name, address, city


def _split_ph_block(block):
    """
    Split  'Name Address City State Zip Phone'  into components.
    Zip, State and Phone are extracted as anchors; the remainder is split
    into name (leading non-address tokens) + address + city.
    Returns (name, address, city, state, zip_, phone).
    """
    name = address = city = state = zip_ = phone = ""

    # ── Phone  (NNN) NNN-NNNN or NNN-NNN-NNNN ──────────────────────────
    ph_m = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', block)
    if ph_m:
        phone = ph_m.group().strip()
        block = block[:ph_m.start()] + " " + block[ph_m.end():]

    # ── ZIP  NNNNN or NNNNN-NNNN ────────────────────────────────────────
    zip_m = re.search(r'\b\d{5}(?:-\d{4})?\b', block)
    if zip_m:
        zip_ = zip_m.group().strip()
        block = block[:zip_m.start()] + " " + block[zip_m.end():]

    # ── State  – last 2-letter known state code before where zip was ────
    for m in re.finditer(r'\b([A-Z]{2})\b', block):
        if m.group() in _STATES:
            state = m.group()
            # Remove just this one occurrence
            block = block[:m.start()] + " " + block[m.end():]
            break

    block = re.sub(r'\s+', ' ', block).strip()

    name, address, city = _split_name_address_city(block)
    return name.strip(), address.strip(), city.strip(), state.strip(), zip_.strip(), phone.strip()


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_fields_from_ocr(text: str) -> dict:
    """
    Parse raw OCR text from one form crop.
    Uses strong anchors (email, P-, C-, Yes/No block) to split text into
    sections, then extracts fields within each section.
    """
    result = {key: "" for key in FIELD_ORDER}

    # ── GLOBAL ANCHORS ─────────────────────────────────────────────────────
    email_m  = re.search(r'[A-Za-z0-9._%+\-]+@(?!LifeIns)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', text)
    policy_m = re.search(r'P-[A-Za-z0-9]{10,}', text)
    card_m   = re.search(r'C-[0-9]{10,}', text)

    email_pos  = email_m.end()    if email_m  else len(text)
    policy_pos = policy_m.start() if policy_m else len(text)
    card_end   = card_m.end()     if card_m   else len(text)

    # First Yes/No in the whole text
    yn_first_m = re.search(r'\b(Yes|No)\b', text, re.IGNORECASE)
    yn_start   = yn_first_m.start() if yn_first_m else len(text)

    # ════════════════════════════════════════════════════════════════════════
    # SECTION A: Header  (start … email)
    # ════════════════════════════════════════════════════════════════════════
    header_end = email_m.start() if email_m else len(text)
    header     = text[:header_end]

    # Record No + Invoice No
    rec_all = re.findall(r'L[-_\s]?[I1][@\s]?(\d{4,6})', text, re.IGNORECASE)
    if len(rec_all) >= 1:
        result["record_no"]  = f"L_I@{rec_all[0]}"
    if len(rec_all) >= 2:
        result["invoice_no"] = f"L_I@{rec_all[1]}"
    if not result["invoice_no"]:
        inv_m2 = re.search(r'(L-Max@LifeIns_21-\d{4,6})', header)
        if inv_m2:
            result["invoice_no"] = inv_m2.group(1).strip()

    # Date of purchase (first date in header)
    dates_hdr = re.findall(r'\d{1,2}/\d{1,2}/\d{4}', header)
    if dates_hdr:
        result["date_of_purchase"] = dates_hdr[0]

    # Cursor within header: skip past record_no, invoice_no, date, then grab
    # customer_id + file_no
    hdr_pos = 0
    for pat in [
        r'L[-_\s]?[I1][@\s]?\d{4,6}',   # record_no
        r'L[-_\s]?[I1][@\s]?\d{4,6}|21-\d{4,6}|L-Max@LifeIns_21-\d{4,6}',  # invoice
        r'\d{1,2}/\d{1,2}/\d{4}',         # date
    ]:
        m = re.search(pat, header[hdr_pos:], re.IGNORECASE)
        if m:
            hdr_pos += m.end()

    cid_m = re.search(r'\b([A-Z0-9]{5,10})\b', header[hdr_pos:], re.IGNORECASE)
    if cid_m:
        result["customer_id"] = cid_m.group().strip()
        hdr_pos += cid_m.end()

    fno_m = re.search(r'\b([A-Za-z0-9]{6,16})\b', header[hdr_pos:])
    if fno_m:
        result["file_no"] = fno_m.group().strip()
        hdr_pos += fno_m.end()

    # PH block: remaining header text
    ph_block = header[hdr_pos:].strip()
    ph_name, ph_addr, ph_city, ph_state, ph_zip, ph_phone = _split_ph_block(ph_block)
    result.update({
        "ph_name": ph_name, "ph_address": ph_addr,
        "ph_city": ph_city, "ph_state": ph_state,
        "ph_zip":  ph_zip,  "ph_phone":  ph_phone,
        "ph_email": email_m.group().strip() if email_m else "",
    })

    # ════════════════════════════════════════════════════════════════════════
    # SECTION B: After email … before policy_no
    # ════════════════════════════════════════════════════════════════════════
    sec_b = text[email_pos:policy_pos].strip()

    # PH DOB: first date
    dob_all = re.findall(r'\d{1,2}/\d{1,2}/\d{4}', sec_b)
    if dob_all:
        result["ph_dob"] = dob_all[0]

    # Education: right after DOB
    edu_pos = 0
    dob_m_b = re.search(r'\d{1,2}/\d{1,2}/\d{4}', sec_b)
    if dob_m_b:
        edu_pos = dob_m_b.end()
    edu_m = re.search(r'N\.A\.|[A-Za-z]{2,}', sec_b[edu_pos:], re.IGNORECASE)
    if edu_m:
        result["education"] = edu_m.group().strip()
        edu_end = edu_pos + edu_m.end()
    else:
        edu_end = edu_pos

    # Blood-group anchor  (AB|A|B|O) + /-
    bg_m = re.search(r'\b(AB|A|B|O)[+\-]', sec_b)
    nominee_end = bg_m.start() if bg_m else len(sec_b)

    # Nominee block
    nominee_block = sec_b[edu_end:nominee_end].strip()

    # Extract ZIP
    nom_zip = ""
    nom_zip_m = re.search(r'\b\d{5}(?:-\d{4})?\b', nominee_block)
    if nom_zip_m:
        nom_zip = nom_zip_m.group().strip()
        nominee_block = nominee_block[:nom_zip_m.start()] + " " + nominee_block[nom_zip_m.end():]

    # Extract State
    nom_state = ""
    for m in re.finditer(r'\b([A-Z]{2})\b', nominee_block):
        if m.group() in _STATES:
            nom_state = m.group()
            nominee_block = nominee_block[:m.start()] + " " + nominee_block[m.end():]
            break

    # Extract Relation with nominee
    nom_rel = ""
    rel_zone_start = sec_b.find(nom_zip, edu_end) + len(nom_zip) if nom_zip and nom_zip in sec_b[edu_end:] else nominee_end - 20
    rel_zone = sec_b[rel_zone_start:nominee_end].strip()
    rel_m = re.search(r'N\.A\.|[A-Za-z]+', rel_zone, re.IGNORECASE)
    if rel_m:
        nom_rel = rel_m.group().strip()
        nominee_block = nominee_block.replace(nom_rel, " ", 1)

    # Extract measurements (last three 2-3 digit numbers)
    meas_nums = re.findall(r'\b\d{2,3}\b', nominee_block)
    chest = height = weight = ""
    if len(meas_nums) >= 3:
        chest = meas_nums[-3]
        height = meas_nums[-2]
        weight = meas_nums[-1]
        for num in meas_nums[-3:]:
            nominee_block = nominee_block.replace(num, " ", 1)
    elif len(meas_nums) == 2:
        height = meas_nums[0]
        weight = meas_nums[1]
        for num in meas_nums[:2]:
            nominee_block = nominee_block.replace(num, " ", 1)

    nominee_block = re.sub(r'\s+', ' ', nominee_block).strip()

    nom_name, nom_addr, nom_city = _split_name_address_city(nominee_block)

    result.update({
        "nominee_name":    nom_name,
        "nominee_address": nom_addr,
        "nominee_city":    nom_city,
        "nominee_state":   nom_state,
        "nominee_zip":     nom_zip,
        "relation_with_nominee": nom_rel,
        "chest": chest,
        "height": height,
        "weight": weight,
    })

    # Blood group
    if bg_m:
        result["blood_group"] = bg_m.group().strip()

    # ════════════════════════════════════════════════════════════════════════
    # SECTION C: policy_no … Yes/No block
    # ════════════════════════════════════════════════════════════════════════
    result["policy_no"] = policy_m.group().strip() if policy_m else ""
    sec_c = text[policy_pos + len(result["policy_no"]):yn_start].strip()

    # Reference No: first long (10+) alphanumeric after policy
    ref_m = re.search(r'\b[A-Za-z0-9]{10,}\b', sec_c)
    if ref_m:
        result["reference_no"] = ref_m.group().strip()
        sec_c_rest = sec_c[ref_m.end():]
    else:
        sec_c_rest = sec_c

    # Plan anchor: "PLAN X" or "PLAN XX"
    plan_m2 = re.search(r'\bPLAN\s+([A-Z])\b', sec_c_rest, re.IGNORECASE)
    agent_raw = sec_c_rest[:plan_m2.start()].strip() if plan_m2 else sec_c_rest

    # Agent codes: last two long (10+) alphanumeric tokens in agent_raw
    ag_codes = re.findall(r'\b[A-Za-z0-9]{10,}\b', agent_raw)
    if len(ag_codes) >= 2:
        result["agent_code"]       = ag_codes[-2]
        result["agent_licence_no"] = ag_codes[-1]
    elif len(ag_codes) == 1:
        result["agent_code"] = ag_codes[0]

    # Remove codes from agent_raw to isolate name/address/city/state/zip
    ag_body = agent_raw
    for code in ag_codes[-2:]:
        ag_body = ag_body.replace(code, " ", 1)

    # Agent state + zip
    ag_zip_m = re.search(r'\b\d{5}(?:-\d{4})?\b', ag_body)
    ag_zip   = ag_zip_m.group().strip() if ag_zip_m else ""
    ag_state = ""
    for m in re.finditer(r'\b([A-Z]{2})\b', ag_body):
        if m.group() in _STATES:
            ag_state = m.group()
            ag_body = ag_body[:m.start()] + " " + ag_body[m.end():]
            break

    if ag_zip:
        ag_body = ag_body.replace(ag_zip, " ", 1)

    ag_body = re.sub(r'\s+', ' ', ag_body).strip()

    ag_name, ag_addr, ag_city = _split_name_address_city(ag_body)

    result.update({
        "agent_name":    ag_name,
        "agent_address": ag_addr,
        "agent_city":    ag_city,
        "agent_state":   ag_state,
        "agent_zip":     ag_zip,
    })

    # Plan name + plan code
    if plan_m2:
        result["plan_name"] = f"PLAN {plan_m2.group(1).upper()}"
        after_plan = sec_c_rest[plan_m2.end():]
        pc_m = re.search(r'\b([A-Za-z0-9]{3,})\b', after_plan)
        if pc_m:
            result["plan_code"] = pc_m.group().strip()

    # Sum of insured + period of insurance (also in sec_c)
    sum_m2 = re.search(r'(\d[\d,]*)\$', sec_c)
    if sum_m2:
        result["sum_of_insured"] = sum_m2.group().strip()
    period_m3 = re.search(r'(\d+)\s*Year', sec_c, re.IGNORECASE)
    if period_m3:
        result["period_of_insurance"] = f"{period_m3.group(1)} Year"

    # ════════════════════════════════════════════════════════════════════════
    # SECTION D: Yes/No block
    # ════════════════════════════════════════════════════════════════════════
    yn_all = re.findall(r'\b(Yes|No)\b', text[yn_start:], re.IGNORECASE)
    for i, key in enumerate(_Q_KEYS):
        if i < len(yn_all):
            result[key] = yn_all[i].capitalize()

    # ════════════════════════════════════════════════════════════════════════
    # SECTION E: After last Yes/No … before card_no
    # ════════════════════════════════════════════════════════════════════════
    yn_last_m = None
    for m in re.finditer(r'\b(Yes|No)\b', text, re.IGNORECASE):
        yn_last_m = m
    pay_start = yn_last_m.end() if yn_last_m else yn_start
    card_start = card_m.start() if card_m else len(text)
    sec_e = text[pay_start:card_start].strip()

    pay_m3 = re.search(
        r'Cash[-\s]?Credit\s+Card|Credit\s+Card|Cheque|enRoute',
        sec_e, re.IGNORECASE
    )
    if pay_m3:
        result["payment_option"] = pay_m3.group().strip()

    pay_amounts = re.findall(r'(\d[\d,]*)\$', sec_e)
    if pay_amounts:
        result["premium"]  = f"{pay_amounts[0]}$"
    if len(pay_amounts) >= 2:
        result["discount"] = f"{pay_amounts[1]}$"

    for ct in _CARD_TYPES:
        if re.search(re.escape(ct), sec_e, re.IGNORECASE):
            result["card_type"] = ct
            break

    # ════════════════════════════════════════════════════════════════════════
    # SECTION F: After card_no
    # ════════════════════════════════════════════════════════════════════════
    result["card_no"] = card_m.group().strip() if card_m else ""
    sec_f = text[card_end:].strip() if card_m else ""

    exp_m = re.search(r'N\.A\.|[A-Za-z0-9./]{3,8}', sec_f, re.IGNORECASE)
    if exp_m:
        result["expiry_date"] = exp_m.group().strip()
        sec_f = sec_f[exp_m.end():].strip()

    # Card holder name: N.A. or name (may contain ?)
    ch_m = re.search(r'N\.A\.|[A-Za-z?][A-Za-z0-9?.\s]{2,40}', sec_f, re.IGNORECASE)
    if ch_m:
        # Don't let it absorb the transaction ID (long alphanum)
        ch_val = ch_m.group().strip()
        # Strip trailing long alphanumeric token (that's transaction_id)
        ch_val = re.sub(r'\s+[A-Za-z0-9]{10,}$', '', ch_val).strip()
        result["card_holder_name"] = ch_val
        sec_f = sec_f[ch_m.end():].strip()

    # Transaction ID: last long alphanumeric
    tid_m = re.search(r'\b[A-Za-z0-9]{10,}\b', text[card_end:])
    if tid_m:
        result["transaction_id"] = tid_m.group().strip()

    # ── Total amount (computed) ────────────────────────────────────────────
    def _to_int(v):
        digits = re.sub(r'[^0-9]', '', str(v or ''))
        return int(digits) if digits else None
    p, d = _to_int(result["premium"]), _to_int(result["discount"])
    if p is not None and d is not None:
        result["total_amount"] = f"{p - d}$"

    return result
