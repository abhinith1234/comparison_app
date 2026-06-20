# OCR Form Validator

An automated checking assistant that validates scanned insurance forms against the data entered into the CRM. It runs local OCR preprocessing on the form image, aligns CRM field entries, and highlights character-level mismatches in an interactive, downloadable validation report.

This project consists of:
- **Backend**: FastAPI + PaddleOCR (open-source local OCR) + OpenCV Preprocessing + RapidFuzz
- **Frontend**: React (Vite)

---

## 🚀 Setup Guide for Complete Beginners

If you are new to the repository and do not have **Python** or **Node.js** installed on your system, follow the steps below for your operating system.

### 📋 Prerequisites & Installation

#### 1. Install Node.js (for the Frontend)
Node.js runs the Vite development server for the user interface.
* **Windows**:
  1. Download the **LTS installer** from [nodejs.org](https://nodejs.org/).
  2. Run the `.msi` installer and follow the instructions (keep the default settings).
* **macOS**:
  * Install via Homebrew: `brew install node`
  * Or download the macOS Installer from [nodejs.org](https://nodejs.org/).
* **Linux (Debian/Ubuntu)**:
  ```bash
  sudo apt-get update
  sudo apt-get install -y nodejs npm
  ```

#### 2. Install Python 3.9+ (for the Backend)
The backend OCR and comparison engine runs on Python.
* **Windows**:
  1. Download the latest Python installer (3.10 or 3.11 is recommended) from [python.org](https://www.python.org/downloads/).
  2. **CRITICAL**: Check the box that says **"Add python.exe to PATH"** before clicking *Install Now*.
  3. Install the **Microsoft Visual C++ Redistributable** (often required by PaddlePaddle library for machine learning modules).
* **macOS**:
  * Install via Homebrew: `brew install python`
* **Linux (Debian/Ubuntu)**:
  ```bash
  sudo apt-get update
  sudo apt-get install -y python3 python3-pip python3-venv
  ```

---

## 🏃 Setup & Run the Application

### Method A: The Double-Click Launcher (Windows – Easiest)

If you are on Windows, you can set up and start the application in a single action:

1. **Double-click `run.bat`** in the project's root folder.
2. *What it does*: 
   * It checks for Python and Node.js. If missing, it will install them automatically using Windows `winget` (you may be asked to approve the prompt).
   * It automatically builds the Python virtual environment (`backend/.venv`), installs dependencies, installs frontend packages, and launches both servers in separate windows.
   * It automatically opens [http://localhost:5173](http://localhost:5173) in your web browser when ready!
3. To stop the application, simply close the two command prompt windows labeled "OCR Backend" and "OCR Frontend".

---

### Method B: Using the Automated Startup Script (macOS / Linux / Bash)

If you have a terminal environment that supports Bash (like Git Bash on Windows, Terminal on macOS, or Linux):

1. **Open your terminal** in the project's root directory (`comparison_app`).
2. **Run the startup script**:
   ```bash
   bash start.sh
   ```
   * *What it does*: It detects your Python version, sets up the virtual environment, installs dependencies, installs frontend modules, and starts both servers.
3. **Open the App**:
   * **Frontend UI**: [http://localhost:5173](http://localhost:5173)
   * **Backend API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

To stop the servers at any time, press `Ctrl + C` in the terminal.

---

### Method C: Manual Setup (Powershell / CMD / Custom)

If you wish to run the commands step-by-step manually:

#### Step 1: Start the Backend
Open a terminal in the project root directory and run:
```powershell
# Navigate to backend directory
cd backend

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Windows CMD:
.venv\Scripts\activate.bat
# On macOS/Linux:
source .venv/bin/activate

# Upgrade pip and install requirements
pip install --upgrade pip
pip install -r requirements.txt

# Start the FastAPI server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

#### Step 2: Start the Frontend
Open a **new, separate terminal** in the project root directory and run:
```powershell
# Navigate to frontend directory
cd frontend

# Install package dependencies
npm install

# Start the React development server
npm run dev
```
Once started, navigate to [http://localhost:5173](http://localhost:5173) in your web browser.

---

## ⚙️ How the Alignment & OCR Works

1. **CRM Seeding**: Stored CRM records are located inside [records.json](file:///n:/comparison_app/comparison_app/backend/data/all_user_forms_details.json).
2. **Preprocessing**: When a form image is uploaded, OpenCV applies grayscale conversion, upscaling, CLAHE contrast enhancement, and unsharp masking to maximize OCR accuracy.
3. **Local Machine Learning**: `PaddleOCR` processes the image locally and reads all text characters.
4. **Field Alignment**: CRM records are mapped to the OCR text positionally using a dynamic programming alignment algorithm.
5. **Exact Diff Matching**: The final verdict is character-exact. If there is a single character difference (other than case/spaces), it flags a red highlight.

For details on how to review the reports, see the full [User Manual](file:///n:/comparison_app/comparison_app/USER_MANUAL.md).

---

## 🛠️ API Reference

| Method | Path             | Purpose                                                |
| ------ | ---------------- | ------------------------------------------------------ |
| `GET`  | `/records`       | Retrieves a list of all stored CRM records             |
| `GET`  | `/records/{key}` | Fetch specific record data by `record_no`               |
| `POST` | `/records`       | Create or update a CRM record                          |
| `POST` | `/validate`      | Submit `form_no` + form image to run OCR and get a diff|
