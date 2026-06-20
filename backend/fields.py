"""Ordered field definitions shared across the backend.

Each entry is (key, serial, label, on_form):
  key      - internal JSON key in the record store
  serial   - serial number exactly as shown in the CRM form (1..57); field 41
             ("Has the life to be insured ever suffered...") has four sub
             sections numbered 41.i .. 41.iv
  label    - field label as shown in the CRM form
  on_form  - whether this field is physically printed on the scanned form box.
             CRM-only fields (Form No, Total Amount, Remark, Submit/Update Date)
             are not on the form, so they cannot be validated against the image.
             Total Amount is derived as Premium - Discount.

List order matches the exact order values appear on the form, which is what the
positional comparator relies on.
"""

FIELDS = [
    # key, serial, label, on_form
    ("form_no", "1", "Form No", False),
    ("record_no", "2", "Record No", True),
    ("invoice_no", "3", "Invoice No", True),
    ("date_of_purchase", "4", "Date of Purchase", True),
    ("customer_id", "5", "Customer Id", True),
    ("file_no", "6", "File No", True),
    ("ph_name", "7", "Policy Holder Name", True),
    ("ph_address", "8", "Policy Holder Address", True),
    ("ph_city", "9", "Policy Holder City", True),
    ("ph_state", "10", "Policy Holder State", True),
    ("ph_zip", "11", "Policy Holder Zip", True),
    ("ph_phone", "12", "Policy Holder Phone", True),
    ("ph_email", "13", "PH Email", True),
    ("ph_dob", "14", "PH DOB", True),
    ("education", "15", "Education", True),
    ("nominee_name", "16", "Nominee Name", True),
    ("nominee_address", "17", "Nominee Address", True),
    ("nominee_city", "18", "Nominee City", True),
    ("nominee_state", "19", "Nominee State", True),
    ("nominee_zip", "20", "Nominee Zip", True),
    ("relation_with_nominee", "21", "Relation With Nominee", True),
    ("chest", "22", "Chest", True),
    ("height", "23", "Height", True),
    ("weight", "24", "Weight", True),
    ("blood_group", "25", "Blood Group", True),
    ("policy_no", "26", "Policy No", True),
    ("reference_no", "27", "Reference No", True),
    ("agent_name", "28", "Agent Name", True),
    ("agent_address", "29", "Agent Address", True),
    ("agent_city", "30", "Agent City", True),
    ("agent_state", "31", "Agent State", True),
    ("agent_zip", "32", "Agent Zip Code", True),
    ("agent_code", "33", "Agent Code", True),
    ("agent_licence_no", "34", "Agent Licence No", True),
    ("plan_name", "35", "Plan Name", True),
    ("plan_code", "36", "Plan Code", True),
    ("sum_of_insured", "37", "Sum Of Insured", True),
    ("period_of_insurance", "38", "Period Of Insurance", True),
    ("q1_alcohol", "39",
     "1. Does the life to be insured consume Alcohol/cigarettes/bidis or tobacco in any form?", True),
    ("q2_medication", "40",
     "2. Is the life to be insured currently taking any medication or drug?", True),
    ("q3a_hypertension", "41.i",
     "3. Has the life to be insured ever suffered or is suffering from - i) Hypertension/high blood pressure", True),
    ("q3b_diabetes", "41.ii", "ii) Diabetes or raised blood sugar", True),
    ("q3c_cardiovascular", "41.iii",
     "iii) Cardiovascular disease, Palpitations, Heart attack, stroke, chest pain", True),
    ("q3d_genitourinary", "41.iv",
     "iv) Genitourinary diseases e.g. Kidney disorder, Bladder disorder, Urine abnormality, renal stones or genital organ disorder", True),
    ("q4_hiv", "42",
     "4. Has the life to be insured ever been tested positive for HIV / AIDS, hepatitis B or C or any sexually transmitted disease?", True),
    ("q5_other_insurance", "43",
     "5. Is the life to be insured currently covered under any health insurance policy with any other company?", True),
    ("q6_involved_pursue", "44",
     "6. Has the life to be insured ever been involved or is planning to pursue any?", True),
    ("q7_glasses", "45", "7. Does the life to be insured wear glasses?", True),
    ("payment_option", "46", "Payment Option", True),
    ("premium", "47", "Premium", True),
    ("discount", "48", "Discount", True),
    ("total_amount", "49", "Total Amount", False),
    ("card_type", "50", "Card Type", True),
    ("card_no", "51", "Card No", True),
    ("expiry_date", "52", "Expiry Date", True),
    ("card_holder_name", "53", "Card Holder Name", True),
    ("transaction_id", "54", "Transaction ID", True),
    ("remark", "55", "Remark", False),
    ("submit_date", "56", "Submit Date", False),
    ("update_date", "57", "Update Date", False),
]

LABELS = {key: label for key, _, label, _ in FIELDS}
SERIALS = {key: serial for key, serial, _, _ in FIELDS}
ON_FORM = {key: on_form for key, _, _, on_form in FIELDS}
FIELD_ORDER = [key for key, _, _, _ in FIELDS]
