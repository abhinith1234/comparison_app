"""Extract scanned insurance form sheets into the CRM column layout (TSV/Excel).

PURE, CRM-INDEPENDENT extraction. Each sheet holds up to ~12 form boxes; the
form prints the field values one after another in a fixed order, wrapping across
lines (a flowing layout, so positions are not fixed). We therefore segment the
OCR token stream into the fixed field order with an order-preserving DP, scoring
each candidate window by how well it matches that field's expected content
(regex shapes + small value vocabularies learned in aggregate from the export -
see field_patterns.py). No per-record CRM lookup is used, so a brand-new record
number is extracted like any other and every column is always emitted.

Pipeline:
  1. detect & crop the form boxes (segmenter),
  2. OCR each crop (ocr_engine; results cached on disk so re-runs are instant),
  3. DP-segment each form's tokens into the field order and read each field,
  4. write one row per form in the exact column order, numeric ID first.

Total Amount is computed as Premium - Discount. Off-form fields (Form No,
Remark, Submit/Update Date) are left blank (they are not printed on the sheet).

Usage:
    python image_to_excel.py latest_data/125/LifeData_001.jpg
    python image_to_excel.py latest_data/125 --out forms_125.tsv
    python image_to_excel.py img1.jpg img2.jpg --xlsx --out forms.xlsx
"""

import argparse
import csv
import hashlib
import os
import pickle
import re
import sys

import cv2

import ocr_engine
import segmenter
from comparator import _total_amount
from fields import FIELDS, FIELD_ORDER, ON_FORM
from field_patterns import LOCATABLE, SPEC, field_score, canonicalize, CODE16, CARD

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CRM = os.path.join(HERE, "data", "all_user_forms_details 2.json")
CACHE_DIR = os.path.join(HERE, ".ocr_cache")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

# Output columns: numeric "ID" then every field except the CRM-only Form No.
OUTPUT_FIELDS = [(k, label) for k, _, label, _ in FIELDS if k != "form_no"]
HEADER = ["ID"] + [label for _, label in OUTPUT_FIELDS]
OFF_FORM_BLANK = {"remark", "submit_date", "update_date"}

REC_ID_RE = re.compile(r"@\s*(\d{4,6})")

# The CRM export uses different key names for some fields; map the internal field
# key (used by FIELDS) -> the key as it appears in the export. Kept in sync with
# main.SOURCE_KEY. Used by field_patterns to learn value vocabularies.
SOURCE_KEY = {
    "ph_name": "policy_holder_name",
    "ph_address": "policy_holder_address",
    "ph_city": "policy_holder_city",
    "ph_state": "policy_holder_state",
    "ph_zip": "policy_holder_zip",
    "ph_phone": "policy_holder_phone",
    "agent_zip": "agent_zip_code",
    "q1_alcohol": "1.does_the_life_to_be_insured_consume_alcohol/cigarettes/bidis_or_tobacco_in_any_form?",
    "q2_medication": "2._is_the_life_to_be_insured_currently_taking_any_medication_or_drug?",
    "q3a_hypertension": "i)_hypertension/high_blood_pressure",
    "q3b_diabetes": "ii)_diabetes_or_raised_blood_sugar",
    "q3c_cardiovascular": "iii)_cardiovascular_disease,_palpitations,_heart_attack,_stroke,_chest_pain",
    "q3d_genitourinary": "iv)_genitourinary_diseases_e.g._kidney_disorder,_bladder_disorder,_urine_abnormality,_renal_stones_or_genital_organ_disorder",
    "q4_hiv": "4.has_the_life_to_be_insured_ever_been_tested_positive_for_hiv_/_aids,_hepatitis_b_or_c_or_any_sexually_transmitted_disease?",
    "q5_other_insurance": "5.is_the_life_to_be_insured_currently_covered_under_any_health_insurance_policy_with_any_other_company?",
    "q6_involved_pursue": "6.has_the_life_to_be_insured_ever_been_involved_or_is_planning_to_pursue_any?",
    "q7_glasses": "7.does_the_life_to_be_insured_wear_glasses?",
}


def normalize_record(raw: dict) -> dict:
    record = {}
    for key in FIELD_ORDER:
        src = SOURCE_KEY.get(key, key)
        if src in raw:
            record[key] = raw[src]
    return record


def record_id(text: str):
    """Numeric record id from a form's OCR text ('L_I@61985' -> '61985')."""
    m = REC_ID_RE.search(text)
    return m.group(1) if m else None


# --- cross-page stitching -----------------------------------------------------
# A form box is one of: a FORM START (begins with the record/invoice marker) that
# is either complete or a top-partial (clipped at a page bottom), or a CONTINUATION
# (no marker) holding the bottom half of a form clipped at the previous page's
# bottom. Forms run in record-number order, so each continuation belongs to the
# oldest still-open top-partial (FIFO).
def _is_form_start(tokens) -> bool:
    return bool(tokens) and bool(REC_ID_RE.search(" ".join(tokens[:2])))


def _is_complete(tokens) -> bool:
    """A full form ends with the Card No / Transaction Id block; a top-partial is
    clipped earlier (at the agent block) and lacks both."""
    if not tokens:
        return False
    if any(CARD.match(t) for t in tokens):
        return True
    if CODE16.match(tokens[-1]):
        return True
    return len(tokens) >= 66


def stitch_texts(seed_pending, texts):
    """Merge form halves split across pages. `seed_pending` carries open
    top-partials from a previous batch (for chunked uploads). Returns
    (completed_texts, still_open_top_partials)."""
    pending = list(seed_pending)
    completed = []
    for t in texts:
        tokens = t.split()
        if not tokens:
            continue
        if _is_form_start(tokens):
            (completed if _is_complete(tokens) else pending).append(t)
        elif pending:
            completed.append(pending.pop(0) + " " + t)
        else:
            completed.append(t)  # orphan bottom-half -> its own row, blank record_no
    return completed, pending


def _row_sort_key(row):
    rid = row[0]
    return (0, int(rid)) if str(rid).isdigit() else (1, 0)


def pure_extract(tokens) -> dict:
    """Order-preserving DP segmentation of the OCR tokens into the fixed field
    order, maximizing each field's content score. Returns {field_key: value}."""
    n, m = len(LOCATABLE), len(tokens)
    NEG = float("-inf")
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    bk = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        key = LOCATABLE[i - 1]
        cap = SPEC[key][1] + 1  # no window longer than the field's max length + 1
        for j in range(m + 1):
            best, bestk = NEG, j
            for k in range(j, max(-1, j - cap - 1), -1):
                prev = dp[i - 1][k]
                if prev == NEG:
                    continue
                val = prev + field_score(key, tokens[k:j])
                if val > best:
                    best, bestk = val, k
            dp[i][j], bk[i][j] = best, bestk

    groups = [None] * n
    j = m
    for i in range(n, 0, -1):
        k = bk[i][j]
        groups[i - 1] = (k, j)
        j = k
    return {
        LOCATABLE[i]: canonicalize(LOCATABLE[i], " ".join(tokens[s:e]).strip())
        for i, (s, e) in enumerate(groups)
    }


def extract_row(text: str) -> list:
    """Build one output row (ID + all columns) from a form's OCR text."""
    # 3. No Extra Spaces & 4. Avoid Double Space
    tokens = re.sub(r"\s+", " ", text).strip().split()
    values = pure_extract(tokens)
    rid = record_id(text) or ""
    row = [rid]
    
    remarks = []
    
    # Pre-process all values
    for key, label in OUTPUT_FIELDS:
        val = values.get(key, "").strip()
        
        # 6. No Inverted Commas
        val = re.sub(r"['\"‘’“”]", "", val)
        
        if ON_FORM.get(key):
            # 5. Missing / Not Applicable Data
            if not val or val.replace(".", "").strip().upper() in ("NA", "N/A"):
                val = "N.A. (AS PER IMAGE)"
                remarks.append(f"{label.upper()} NOT GIVEN")
            else:
                # 1. Phone Number
                if "phone" in key.lower():
                    digits = re.sub(r"\D", "", val)
                    if len(digits) < 10:
                        remarks.append("PHONE NO. INVALID")
                
                # 2. ZIP Code
                if "zip" in key.lower():
                    digits = re.sub(r"\D", "", val)
                    if len(digits) < 5:
                        remarks.append("ZIP INVALID")
        
        values[key] = val

    for key, _ in OUTPUT_FIELDS:
        if key == "record_no":
            row.append(f"L_I@{rid}" if rid else (values.get("record_no") or ""))
        elif key == "total_amount":
            row.append(_total_amount(values.get("premium", ""), values.get("discount", "")))
        elif key == "remark":
            row.append(", ".join(remarks))
        elif key in OFF_FORM_BLANK or not ON_FORM.get(key):
            row.append("")
        else:
            row.append(values.get(key, ""))
            
    return row


def gather_images(paths) -> list:
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for fn in sorted(files):
                    if fn.lower().endswith(IMAGE_EXTS):
                        out.append(os.path.join(root, fn))
        elif os.path.isfile(p) and p.lower().endswith(IMAGE_EXTS):
            out.append(p)
        else:
            print(f"  ! skipping (not an image/folder): {p}", file=sys.stderr)
    return out


def _cache_path(img_path):
    st = os.stat(img_path)
    sig = f"{os.path.abspath(img_path)}|{st.st_size}|{int(st.st_mtime)}"
    return os.path.join(CACHE_DIR, hashlib.md5(sig.encode()).hexdigest() + ".pkl")


def _ocr_sheet(img_path):
    bgr = cv2.imread(img_path)
    if bgr is None:
        print(f"  ! could not read {img_path}", file=sys.stderr)
        return []
    crops = segmenter.crop_boxes(bgr, segmenter.detect_form_boxes(bgr))
    payloads = [cv2.imencode(".png", c)[1].tobytes() for c in crops]
    texts = ocr_engine.extract_text_batch(payloads)
    return [{"index": i, "text": t} for i, t in enumerate(texts)]


def ocr_forms(image_paths, use_cache=True):
    os.makedirs(CACHE_DIR, exist_ok=True)
    forms = []
    for img_path in image_paths:
        cpath = _cache_path(img_path)
        if use_cache and os.path.exists(cpath):
            with open(cpath, "rb") as f:
                sheet = pickle.load(f)
            tag = "cache"
        else:
            sheet = _ocr_sheet(img_path)
            with open(cpath, "wb") as f:
                pickle.dump(sheet, f)
            tag = "OCR"
        print(f"  {tag} {os.path.basename(img_path)}: {len(sheet)} forms")
        forms.extend(sheet)
    return forms


def write_tsv(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(HEADER)
        w.writerows(rows)


def write_xlsx(rows, out_path):
    try:
        from openpyxl import Workbook
    except ImportError:
        raise SystemExit("openpyxl not installed; run: pip install openpyxl (or drop --xlsx for TSV)")
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    wb.save(out_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract form sheet images into the CRM column layout (CRM-independent).")
    ap.add_argument("inputs", nargs="+", help="image file(s) and/or folder(s) of sheet images")
    ap.add_argument("--out", default=None, help="output path (default: extracted_forms.tsv / .xlsx)")
    ap.add_argument("--xlsx", action="store_true", help="write an .xlsx workbook instead of TSV")
    ap.add_argument("--no-cache", action="store_true", help="ignore the on-disk OCR cache")
    args = ap.parse_args(argv)

    images = gather_images(args.inputs)
    if not images:
        raise SystemExit("No images found.")
    print(f"Found {len(images)} sheet image(s).")

    forms = ocr_forms(images, use_cache=not args.no_cache)
    if not forms:
        raise SystemExit("No form boxes detected.")

    completed, pending = stitch_texts([], [f["text"] for f in forms])
    rows = [extract_row(t) for t in completed + pending]  # flush open top-partials too
    rows.sort(key=_row_sort_key)
    print(f"Extracted {len(rows)} form(s) (stitched {len(forms)} boxes).")

    out = args.out or ("extracted_forms.xlsx" if args.xlsx else "extracted_forms.tsv")
    if args.xlsx:
        write_xlsx(rows, out)
    else:
        write_tsv(rows, out)
    print(f"Wrote -> {out}")


if __name__ == "__main__":
    main()
