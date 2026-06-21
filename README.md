# OCR Form Extractor & Validator

A tool that:
1. **Extracts** scanned insurance form images into a structured Excel spreadsheet (no CRM data needed).
2. **Validates** scanned forms against CRM data, highlighting character-level mismatches.

**Stack:**
- **Backend**: FastAPI + PaddleOCR (local, offline OCR) + OpenCV preprocessing + RapidFuzz
- **Frontend**: React (Vite)

---

## 📋 Prerequisites

| Tool | Minimum Version | Notes |
|------|----------------|-------|
| **Python** | 3.9 – 3.11 | 3.10 or 3.11 recommended |
| **Node.js** | 18 LTS or newer | Includes `npm` |
| **Git** | Any | To clone the repo |
| **Microsoft Visual C++ Redistributable** | 2015–2022 | Windows only – required by PaddlePaddle |

> **GPU (optional):** If you have an NVIDIA GPU with CUDA 11.x / 12.x, PaddleOCR will automatically use it and run ~5× faster. CPU works fine out of the box.

---

## 🚀 Quick Setup

### Windows – Double-Click (Easiest)

1. **Double-click `run.bat`** in the project root folder.
2. The script will:
   - Install Python and Node.js via `winget` if missing (you may be prompted to approve).
   - Create a Python virtual environment and install all backend dependencies.
   - Install frontend packages with `npm install`.
   - Start both servers and open [http://localhost:5173](http://localhost:5173) in your browser.
3. To stop: close the two terminal windows labelled **"OCR Backend"** and **"OCR Frontend"**.

---

### macOS / Linux – Shell Script

```bash
# From the project root
bash start.sh
```

The script sets up the virtual environment, installs everything, and starts both servers.

- **App UI**: [http://localhost:5173](http://localhost:5173)
- **API docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

Press `Ctrl + C` to stop.

---

### Manual Setup (PowerShell / CMD / Any OS)

#### Step 1 – Backend

```powershell
cd backend

# Create and activate a virtual environment
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1
# Windows CMD
.venv\Scripts\activate.bat
# macOS / Linux
source .venv/bin/activate

# Install dependencies (includes PaddleOCR, OpenCV, FastAPI, etc.)
pip install --upgrade pip
pip install -r requirements.txt

# Start the API server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

#### Step 2 – Frontend

Open a **new separate terminal** in the project root:

```powershell
cd frontend

npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

---

## ⚠️ First-Run Notes

- **PaddleOCR model download**: The first time the backend handles an image, PaddleOCR will automatically download its OCR model files (~150 MB). This is a one-time download and requires an internet connection.  
- **OCR cache**: Once an image is OCR'd, results are cached locally in `backend/.ocr_cache/`. Re-uploading the same image is instant.
- **Windows "Execution Policy" error** when running `.venv\Scripts\Activate.ps1`: Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` in PowerShell, then try again.

---

## 🖼️ Using the Image-to-Excel Extractor

1. Open the app at [http://localhost:5173](http://localhost:5173).
2. Click **"OCR Extract to Excel"** (or the equivalent tab).
3. Upload one or more scanned sheet images (`.jpg`, `.png`, `.bmp`, `.tif`).
   - If you have multi-page scans, upload all pages **together** – the system sorts them by filename automatically (name them sequentially, e.g. `LifeData_001.jpg`, `LifeData_002.jpg`).
4. Click **Extract**. A progress bar shows per-image progress.
5. When complete, an `.xlsx` file downloads automatically.

**What the extractor produces:**
- One row per form box detected in the images.
- All 60 CRM columns filled (Record No, Policy Holder, Nominee, Agent, Plan, Payment, etc.).
- A **Remarks** column with validation notes (e.g. `PHONE NO. INVALID`, `ZIP INVALID`).
- Cross-page forms (where a form box is split across two pages) are automatically stitched together.

---

## ✅ Using the CRM Validator

1. Upload the CRM export JSON to `backend/data/all_user_forms_details 2.json` (replace existing file).
2. In the app, select a **CRM Record** from the dropdown.
3. Upload the matching **scanned form image**.
4. Click **Validate** – a field-by-field comparison report downloads automatically.

---

## ⚙️ How It Works

1. **Segmentation**: OpenCV detects and crops individual form boxes from each sheet image.
2. **Preprocessing**: Each crop is upscaled, deskewed, CLAHE-enhanced, denoised, and sharpened before OCR.
3. **OCR**: PaddleOCR (PP-OCRv4, offline) reads text from each crop.
4. **Extraction (DP)**: An order-preserving dynamic-programming segmenter assigns each OCR token to one of the 60 fixed fields using per-field content scorers.
5. **Stitching**: Forms split across page boundaries are detected and merged automatically.
6. **Output**: Rows are written to Excel, sorted by Record ID.

---

## 🛠️ API Reference

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/records` | List all CRM records |
| `GET` | `/records/{key}` | Fetch a record by `record_no` |
| `POST` | `/records` | Create / update a CRM record |
| `POST` | `/validate` | OCR + diff a form image against a CRM record |
| `POST` | `/extract` | Extract form images → structured rows (used by the Excel exporter) |
| `POST` | `/ocr` | Raw OCR of an uploaded image |

Full interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🗂️ Project Structure

```
comparison_app/
├── backend/
│   ├── main.py              # FastAPI app + all endpoints
│   ├── image_to_excel.py    # OCR extraction pipeline (DP segmenter, stitching)
│   ├── field_patterns.py    # Per-field scorers + canonicalisation rules
│   ├── fields.py            # Field definitions (60 columns, order, labels)
│   ├── segmenter.py         # Form-box detection (OpenCV)
│   ├── ocr_engine.py        # PaddleOCR wrapper + image preprocessing
│   ├── comparator.py        # CRM vs OCR field comparison
│   ├── requirements.txt     # Python dependencies
│   └── data/                # CRM export JSON lives here
└── frontend/
    ├── src/
    │   ├── App.jsx          # Main UI (extractor + validator)
    │   └── styles.css
    └── package.json
```
