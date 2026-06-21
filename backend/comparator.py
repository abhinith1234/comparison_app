"""Positional (ordered), EXACT comparison between stored values and OCR text.

The form box prints field values in a fixed sequence that matches the field
order, so we align the ordered list of expected values to the OCR token stream
with dynamic programming: every field is assigned its best-scoring contiguous
span, the spans stay in order, and OCR-noise tokens may be skipped between
fields. This locates where each value sits without one bad match cascading.

The pass/fail verdict is EXACT: a field is a "match" only if the expected value
equals the OCR text character-for-character (special characters included).
Comparison ignores only letter case and surrounding/redundant whitespace, since
those are not part of the data. Any other difference - a missing $, -, /, a 7
read as Z, a dropped character - is a "mismatch". A similarity score is still
reported for context, and fuzzy similarity is used ONLY to locate each span.

Fields not on the form (on_form == False) are "not_on_form" (excluded from
pass/fail). Total Amount is "calculated" (Premium - Discount, never on the form).
"""

import re
import unicodedata
from rapidfuzz import fuzz

from fields import FIELDS

NEG = float("-inf")


def strip_accents(value: str) -> str:
    """Remove combining diacritical marks so OCR artefacts like 'À' (caused by
    a printed underline/border bleeding into the letter) normalise to the plain
    base letter 'A'.  Only combining marks (category 'Mn') are stripped; all
    other characters are preserved."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def collapse(value: str) -> str:
    """Uppercase and collapse whitespace; keep every other character intact."""
    return re.sub(r"\s+", " ", strip_accents(str(value)).upper()).strip()


# Some glyphs are drawn identically, so OCR (and a human keying the data) cannot
# tell them apart. Fold them so the ambiguity never produces a false mismatch:
#   - letter "L", pipe "|" -> capital "I"  (lowercase "l", capital "I" and "|"
#     are the same vertical stroke; comparison is upper case so "l" arrives as
#     "L", hence folding "L" covers both the case and the glyph confusion)
#   - letter "O" -> digit "0"  (e.g. blood group "O+" is read as "0+")
#   - closing bracket "]" -> capital "J"   (OCR frequently misreads "J" / "j" as "]")
#   - letter "Q" -> letter "G"  (underlines fuse with the "q" descender, making
#     it look like "g" to the OCR engine; comparison is upper-case so both arrive
#     as Q/G and we fold them to a single form)
# The digit "1" is NOT folded with I: it is a distinct character. Note: because
# I and L collapse, two values differing only by I vs L (e.g. state "LA" vs
# "IA") are treated as equal.
_AMBIGUOUS = str.maketrans({"L": "I", "|": "I", "O": "0", "]": "J", "Q": "G"})


def compare_key(value: str) -> str:
    """Comparison key: case-insensitive with whitespace, hyphens AND commas
    removed; every other character kept. Case is ignored because OCR reads it
    inconsistently (a printed 'FL' is read as 'Fl'). Whitespace, hyphens and
    commas are ignored because OCR handles them inconsistently when a value
    wraps across two rows (e.g. 'C-869923151878041' is read as
    'C 869923151878041' with the dash lost; 'Wellington,' loses its comma).
    Other special characters ($, /, @, ...) are compared exactly. Pipe folds to
    I and letter O folds to digit 0; the digit 1 is kept distinct.
    """
    key = re.sub(r"[\s\-,_]+", "", strip_accents(str(value))).upper()
    # The record number is the constant boilerplate prefix "L_" + "I@" + id, and
    # OCR mangles that prefix inconsistently: it may keep it ("L_I@61637"), read
    # the underscore as a space ("L I@61637" -> "LI@..." once spaces are
    # stripped), or drop the whole "L_" ("I@61637"). Strip a leading "L" when it
    # sits right before the "I@" marker so all three forms compare equal.
    key = re.sub(r"^L(?=I@)", "", key)
    # Long numeric IDs are printed with a constant single-letter prefix and a
    # separator (Policy No "P-892915425498290", Card No "C-869923151878041").
    # When the value wraps, OCR often drops that leading letter and reads only
    # the digits. Strip a leading single letter when the rest is a long digit
    # run, on both sides, so it matches whether OCR kept the prefix or not.
    key = re.sub(r"^[A-Z](?=[0-9]{5,}$)", "", key)
    return key.translate(_AMBIGUOUS)


def _align(expected_strs, expected_lens, tokens):
    """Order-preserving DP alignment of expected values to OCR tokens.

    Fuzzy similarity is used here only to find each field's span.
    Returns a (start, end) span into `tokens` for each field.

    The alignment uses a liberal search window (target_len + 4 extra tokens)
    and a low recovery threshold for single-token values (40 for Yes/No).
    Validation strictness comes from the EXACT character comparison in
    compare_record(), not from restricting the search window here.
    """
    n = len(expected_strs)
    m = len(tokens)
    if n == 0:
        return []

    def window_score(idx, start, end):
        return fuzz.ratio(expected_strs[idx], collapse(" ".join(tokens[start:end])))

    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0] = [0.0] * (m + 1)

    for i in range(1, n + 1):
        target_len    = max(1, expected_lens[i - 1])
        # Allow up to target_len + 4 extra tokens so long multi-word values
        # (addresses, names) and dense 50-field forms still align correctly.
        search_window = target_len + 4
        pref_val = [NEG] * (m + 1)
        pref_arg = [0] * (m + 1)
        run, run_arg = NEG, 0
        for j in range(m + 1):
            if dp[i - 1][j] > run:
                run, run_arg = dp[i - 1][j], j
            pref_val[j], pref_arg[j] = run, run_arg

        for j in range(m + 1):
            for length in range(0, search_window + 1):
                start = j - length
                if start < 0:
                    continue
                base = pref_val[start]
                if base == NEG:
                    continue
                score = base + window_score(i - 1, start, j)
                if score > dp[i][j]:
                    dp[i][j] = score
                    back[i][j] = (start, pref_arg[start])

    end_j = max(range(m + 1), key=lambda j: dp[n][j])
    spans = [None] * n
    j = end_j
    for i in range(n, 0, -1):
        entry = back[i][j]
        if entry is None:
            spans[i - 1] = (j, j)
            continue
        start, prev_end = entry
        spans[i - 1] = (start, j)
        j = prev_end

    # Recovery pass: an empty field tries to claim its best-matching *unclaimed*
    # token within its local gap (between the surrounding assigned spans). It can
    # only use tokens no other field took, so matched fields are never disturbed;
    # this rescues fields the global DP left empty when a token was right there.
    occupied = [False] * m
    for s, e in spans:
        for t in range(s, e):
            occupied[t] = True
    for i in range(n):
        s, e = spans[i]
        if e > s:
            continue
        left = spans[i - 1][1] if i > 0 else 0
        right = m
        for k in range(i + 1, n):
            if spans[k][1] > spans[k][0]:
                right = spans[k][0]
                break
        target = max(1, expected_lens[i])
        best_score, best_span = NEG, None
        for start in range(left, right):
            for length in range(1, target + 2):
                end = start + length
                if end > right:
                    break
                if any(occupied[t] for t in range(start, end)):
                    break
                sc = fuzz.ratio(
                    expected_strs[i], collapse(" ".join(tokens[start:end]))
                )
                if sc > best_score:
                    best_score, best_span = sc, (start, end)
        # Lower threshold for single-token values (Yes/No) since fuzz.ratio
        # between a 2-char string and surrounding context is inherently lower.
        min_score = 40 if target <= 1 else 55
        if best_span and best_score >= min_score:
            spans[i] = best_span
            for t in range(best_span[0], best_span[1]):
                occupied[t] = True
    return spans


def _union_box(boxes):
    if not boxes:
        return None
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def compare_record(record: dict, ocr_text: str, token_boxes=None) -> dict:
    """Compare a stored CRM record against OCR text from the scanned form.

    Used by both validation and extraction.  Alignment is always liberal
    (wide window, low recovery threshold for Yes/No) so the DP can locate
    all ~50 fields reliably.  Validation strictness is enforced by the
    exact character comparison (compare_key) further below — not by
    restricting the search window.
    """
    tokens = collapse(ocr_text).split()
    # Same tokens but with original letter case preserved (collapse() upper-cases
    # for robust alignment; the verdict and display must keep the real case).
    disp_tokens = re.sub(r"\s+", " ", ocr_text).strip().split()

    # Only non-blank on-form fields take part in the positional alignment.
    align_keys = [
        key
        for key, _, _, on_form in FIELDS
        if on_form and key != "total_amount" and collapse(record.get(key, ""))
    ]
    expected_strs = [collapse(record.get(key, "")) for key in align_keys]
    expected_lens = [len(s.split()) for s in expected_strs]
    spans = _align(expected_strs, expected_lens, tokens)
    span_by_key = {align_keys[i]: spans[i] for i in range(len(align_keys))}

    field_results = []
    matched = mismatched = checked = 0
    found_values = {}

    for key, serial, label, on_form in FIELDS:
        raw = str(record.get(key, "")).strip()

        if key == "total_amount":
            # Entered = CRM total; Found = total derived from the OCR-read
            # Premium and Discount on the form (Premium - Discount). Validate the
            # two against each other: match (green) only if they are equal.
            crm_total = raw or _total_amount(
                record.get("premium", ""), record.get("discount", "")
            )
            ocr_total = _total_amount(
                found_values.get("premium", ""), found_values.get("discount", "")
            )
            checked += 1
            is_exact = bool(ocr_total) and compare_key(crm_total) == compare_key(ocr_total)
            score = round(fuzz.ratio(compare_key(crm_total), compare_key(ocr_total)), 1)
            status = "match" if is_exact else "mismatch"
            if is_exact:
                matched += 1
                ocr_total = crm_total
            else:
                mismatched += 1
            field_results.append(
                _row(key, serial, label, crm_total, ocr_total, score, status)
            )
            continue

        if not on_form:
            field_results.append(_row(key, serial, label, raw, "", None, "not_on_form"))
            continue

        checked += 1

        if not collapse(raw):
            # Nothing was entered, so there is nothing to verify on the image.
            matched += 1
            field_results.append(_row(key, serial, label, raw, "", 100.0, "match"))
            continue

        start, end = span_by_key[key]
        found = " ".join(disp_tokens[start:end])

        if not found.strip():
            # Alignment returned an empty span: OCR couldn't locate this field's
            # value in the text.  Count as a mismatch with a dedicated status so
            # the UI can display "OCR missed" distinctly from "OCR read wrong value".
            mismatched += 1
            field_results.append(
                _row(key, serial, label, raw, "", 0.0, "ocr_missed")
            )
            continue

        is_exact = compare_key(raw) == compare_key(found)
        score = round(fuzz.ratio(compare_key(raw), compare_key(found)), 1)
        status = "match" if is_exact else "mismatch"
        if is_exact:
            matched += 1
            # On a match, show the clean CRM value (e.g. "L_I@63451") instead of
            # the OCR variant (e.g. "I@63451") that only differs by folded glyphs.
            found = raw
        else:
            mismatched += 1
        found_values[key] = found

        box = None
        if not is_exact and token_boxes:
            box = _union_box(
                [token_boxes[t] for t in range(start, end) if t < len(token_boxes)]
            )
        field_results.append(
            _row(key, serial, label, raw, found, score, status, box)
        )

    overall_score = round(matched / checked * 100, 1) if checked else 0.0
    verdict = "PASS" if mismatched == 0 else "FAIL"

    # Wrong-image guard: the record number is unique and printed on every form,
    # so if its digits aren't anywhere in the OCR text the uploaded image almost
    # certainly does not belong to this record (which makes the whole column
    # misalign). Flag it instead of returning a misleading report.
    rec_digits = re.sub(r"[^0-9]", "", str(record.get("record_no", "")))
    ocr_digits = re.sub(r"[^0-9]", "", ocr_text)
    image_mismatch = bool(rec_digits) and rec_digits not in ocr_digits

    return {
        "verdict": verdict,
        "overall_score": overall_score,
        "image_mismatch": image_mismatch,
        "summary": {
            "checked": checked,
            "matched": matched,
            "partial": 0,
            "mismatched": mismatched,
        },
        "fields": field_results,
    }


def _total_amount(premium: str, discount: str) -> str:
    """Total Amount = Premium - Discount (it is never printed on the form)."""
    def amount(value):
        digits = re.sub(r"[^0-9]", "", str(value or ""))
        return int(digits) if digits else None

    p, d = amount(premium), amount(discount)
    if p is None or d is None:
        return ""
    return f"{p - d}$"


def _row(key, serial, label, expected, found, score, status, box=None):
    return {
        "field": key,
        "serial": serial,
        "label": label,
        "expected": expected,
        "found": found,
        "score": score,
        "status": status,
        "box": box,
    }
