import time

import cv2  # noqa: F401
from paddleocr import PaddleOCR

import ocr_engine
from comparator import compare_record

RAW = open("/tmp/form_61023.png", "rb").read()
REC = {
    "record_no": "L_I@61023", "invoice_no": "L-Max@LifeIns_21-61023",
    "date_of_purchase": "1/6/2022", "customer_id": "7PIQEL9", "file_no": "7GF1kYX1ya",
    "ph_name": "Nathaniel C Hensley", "ph_address": "607 HUNTINGTON ST",
    "ph_city": "S CLARA", "ph_state": "CA", "ph_zip": "44341",
    "ph_phone": "(239) 657-4490", "ph_email": "mail@test.com", "ph_dob": "1/22/1999",
    "education": "N.A.", "nominee_name": "Diane D Marshall",
    "nominee_address": "607 HUNTINGTON ST", "nominee_city": "S CLARA",
    "nominee_state": "CA", "nominee_zip": "44341", "relation_with_nominee": "N.A.",
    "chest": "72", "height": "156", "weight": "142", "blood_group": "B+",
    "policy_no": "P-917549843325666", "reference_no": "JkYoqg8mSIQp8WDR",
    "agent_name": "American Income Life Insurance Company", "agent_city": "Waco",
    "agent_state": "Texas", "agent_code": "479g8wdBGDiCzW5q",
    "agent_licence_no": "Jc0kuEI5XD16dYjH", "plan_name": "PLAN M", "plan_code": "U84coDX",
    "sum_of_insured": "5000$", "period_of_insurance": "1 Year",
    "q1_alcohol": "No", "q2_medication": "No", "q3a_hypertension": "No",
    "q3b_diabetes": "No", "q3c_cardiovascular": "No", "q3d_genitourinary": "No",
    "q4_hiv": "No", "q5_other_insurance": "No", "q6_involved_pursue": "No",
    "q7_glasses": "Yes", "payment_option": "Credit Card", "premium": "460$",
    "discount": "45$", "total_amount": "415$", "card_type": "JCB",
    "card_no": "C-3337948264024561", "expiry_date": "N.A.",
    "card_holder_name": "Nathaniel C Hensley", "transaction_id": "HbihjPY4DwVPWdFE",
}


def run_paddle(ocr, bgr):
    res = ocr.predict(bgr)[0]
    texts = res.get("rec_texts") or []
    polys = res.get("rec_polys")
    if polys is None:
        polys = res.get("dt_polys") or res.get("rec_boxes") or []
    return ocr_engine._reading_order(texts, polys)


def build(variant):
    common = dict(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    if variant == "mobile":
        common.update(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
        )
    return PaddleOCR(**common)


def bench(label, ocr, width):
    ocr_engine.TARGET_WIDTH = width
    bgr = ocr_engine._preprocess(RAW)
    run_paddle(ocr, bgr)  # warm
    t = time.time()
    txt = run_paddle(ocr, bgr)
    dt = time.time() - t
    s = compare_record(REC, txt)["summary"]
    print(f"{label:22} width={width:5}  time={dt:5.2f}s  matched={s['matched']}/{s['checked']}")


if __name__ == "__main__":
    default = build("default")
    bench("default", default, 1800)
    bench("default", default, 1280)
    mobile = build("mobile")
    bench("mobile", mobile, 1800)
    bench("mobile", mobile, 1280)
    bench("mobile", mobile, 960)
