"""Diagnostic: show exactly what OCR read and how each field aligned.

Usage:
    ./venv/bin/python debug_validate.py /path/to/form_image.jpg 61638

The second argument is any part of the record number (e.g. 61638 or L_I@61638).
Paste the whole output back for diagnosis.
"""
import sys

import main
import ocr_engine
from comparator import collapse, compare_record


def main_cli():
    if len(sys.argv) < 3:
        print("usage: python debug_validate.py <image_path> <record_no_substring>")
        return
    image_path, needle = sys.argv[1], sys.argv[2]

    records = main.load_records()
    matches = [r for r in records if needle in str(r.get("record_no", ""))]
    if not matches:
        print(f"No record contains {needle!r}")
        return
    record = matches[0]
    print(f"RECORD: {record.get('record_no')}  (form {record.get('form_no')})\n")

    ocr_text = ocr_engine.extract_text(open(image_path, "rb").read())

    print("=" * 70)
    print("RAW OCR TEXT")
    print("=" * 70)
    print(ocr_text)

    print("\n" + "=" * 70)
    print("TOKENS (index: token)")
    print("=" * 70)
    for i, tok in enumerate(ocr_text.split()):
        print(f"  {i:3}: {tok}")

    # Is each problem value present anywhere in the OCR?
    print("\n" + "=" * 70)
    print("VALUE PRESENCE CHECK (whitespace/case-insensitive contains)")
    print("=" * 70)
    flat = collapse(ocr_text)
    for key in ("nominee_zip", "plan_code", "reference_no"):
        val = collapse(record.get(key, ""))
        print(f"  {key:14} expected={record.get(key)!r:24} in OCR? {val in flat}")

    res = compare_record(record, ocr_text)
    print("\n" + "=" * 70)
    print(f"RESULT  verdict={res['verdict']}  score={res['overall_score']}  "
          f"image_mismatch={res['image_mismatch']}  {res['summary']}")
    print("=" * 70)
    for f in res["fields"]:
        if f["status"] in ("match", "mismatch"):
            flag = "" if f["status"] == "match" else "  <<<"
            print(f"  {f['serial']:>5} {f['label'][:34]:34} | "
                  f"exp={f['expected']!r:26} found={f['found']!r:26} "
                  f"{f['status']}{flag}")


if __name__ == "__main__":
    main_cli()
