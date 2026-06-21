import sys, json, re
sys.path.insert(0, r'n:\comparison_app\comparison_app\backend')

from ocr_engine import extract_text
from extractor import extract_fields_from_ocr
from fields import FIELD_ORDER

# Load first scraped record to find a real image, or just test with real OCR text
# Instead, load the scraped JSON and check what the raw values look like
data = json.load(open(r'n:\comparison_app\comparison_app\backend\data\scraped_20260620_144736.json', encoding='utf-8'))
r = data[0]

# Print what fields have values in CRM (so we know what to expect from OCR)
print("=== CRM VALUES FOR RECORD 0 ===")
for k in FIELD_ORDER:
    v = r.get(k, '')
    if v:
        print(f"  {k}: {v!r}")

# Now simulate OCR text that would come from the form for this record
# (reconstruct the approximate form text)
parts = []
for k in ['record_no','invoice_no','date_of_purchase','customer_id','file_no']:
    v = r.get(k, '')
    if v: parts.append(str(v))

ph_parts = [r.get('ph_name',''), r.get('ph_address',''), r.get('ph_city',''),
            r.get('ph_state',''), r.get('ph_zip',''), r.get('ph_phone',''), r.get('ph_email','')]
parts.extend([p for p in ph_parts if p])

for k in ['ph_dob','education','nominee_name','nominee_address','nominee_city','nominee_state','nominee_zip','relation_with_nominee']:
    v = r.get(k,'')
    if v: parts.append(str(v))

for k in ['chest','height','weight','blood_group']:
    v = r.get(k,'')
    if v: parts.append(str(v))

parts.append(r.get('policy_no',''))
parts.append(r.get('reference_no',''))

for k in ['agent_name','agent_address','agent_city','agent_state','agent_zip','agent_code','agent_licence_no']:
    v = r.get(k,'')
    if v: parts.append(str(v))

for k in ['plan_name','plan_code','sum_of_insured','period_of_insurance']:
    v = r.get(k,'')
    if v: parts.append(str(v))

for k in ['q1_alcohol','q2_medication','q3a_hypertension','q3b_diabetes','q3c_cardiovascular',
          'q3d_genitourinary','q4_hiv','q5_other_insurance','q6_involved_pursue','q7_glasses']:
    v = r.get(k,'')
    if v: parts.append(str(v))

for k in ['payment_option','premium','discount','card_type','card_no','expiry_date','card_holder_name','transaction_id']:
    v = r.get(k,'')
    if v: parts.append(str(v))

simulated = ' '.join(str(p) for p in parts if p)
print(f"\n=== SIMULATED OCR TEXT ===\n{simulated}\n")

result = extract_fields_from_ocr(simulated)
print("=== EXTRACTOR RESULTS ===")
for k in FIELD_ORDER:
    expected = str(r.get(k, '')).strip()
    got = str(result.get(k, '')).strip()
    if not expected:
        continue
    status = "OK" if got else "EMPTY" if not got else "MISMATCH"
    if got and got != expected:
        status = "DIFF"
    print(f"  [{status}] {k}: got={got!r}  expected={expected!r}")
