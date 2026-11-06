FinSight AI 🛡️📊
Bank Statement Intelligence & Financial Health Analyzer

FinSight AI is a privacy-first, fully local full-stack platform built to transform raw bank statements into explainable financial intelligence. Designed specifically for the Problem 04: AI-Based Bank Statement Intelligence and Financial Health Analyzer hackathon challenge, this system processes financial documents, categorizes spending, detects recurring patterns, and flags anomalies without ever sending sensitive data to external cloud APIs.

🚀 Key Differentiators (Why This Wins)
Zero-Cloud Privacy Architecture: Unlike typical AI wrappers, 100% of transaction processing, ML classification, and anomaly detection runs locally. Sensitive financial records never leave the user's machine.

Deterministic Ledger Reconciliation: Extracts data from CSV, Excel, and Text-PDFs and runs a strict mathematical validation (Opening + Credits - Debits = Closing) on every row before import.

4-Layer Hybrid Categorization Engine: Combines user-defined rules, regional regex patterns, and a dynamic scikit-learn TF-IDF classifier that learns from the user's verified history.

Explainable, Non-Accusatory Anomaly Detection: Uses Median Absolute Deviation (MAD) and Isolation Forests to catch outliers. It strictly uses cautious language ("Review Recommended") rather than black-box "Fraud" labels.

Transparent Financial Health Score: A 100-point normalized index based on a fully explainable 5-pillar mathematical model (Savings Rate, Cash Flow Stability, Spending Control, Recurring Burden, Expense Volatility).

🛠️ Tech Stack
Backend

Framework: Python, FastAPI

Data Science & ML: Pandas, NumPy, Scikit-Learn (TF-IDF, LogisticRegression, IsolationForest)

Document Intelligence: PyMuPDF (fitz), OpenPyXL

Database: SQLite (dev) / PostgreSQL (prod) via SQLAlchemy ORM

Security: Passlib, JWT Authentication

Frontend

Framework: React 18 with TypeScript, Vite

Styling: Tailwind CSS

Data Visualization: Recharts, Chart.js

Icons: Lucide React

📂 Project Structure
Plaintext
finsight-ai/
├── backend/
│   ├── app/
│   │   ├── services/
│   │   │   ├── parser.py         # Multi-format ingestion & ledger validation
│   │   │   ├── intelligence.py   # Hybrid ML categorizer & Anomaly detector
│   │   │   ├── reports.py        # PDF/CSV/Excel exporter
│   │   │   └── demo_seeder.py    # Synthetic 3-month dataset generator
│   │   ├── main.py               # FastAPI router
│   │   ├── models.py             # SQLAlchemy DB schemas
│   │   ├── security.py           # JWT & Auth
│   │   └── ...
│   ├── tests/                    # Pytest suite
│   ├── requirements.txt
│   └── generate_sample_files.py  # Generates test bank statements
└── frontend/
    ├── src/
    │   ├── App.tsx               # Main React Dashboard
    │   ├── main.tsx              
    │   └── index.css
    ├── tailwind.config.js
    └── package.json
⚙️ Local Setup & Installation (Windows PowerShell)
1. Start the Backend
Open a PowerShell terminal and navigate to the root repository folder.

PowerShell
# Move into the backend directory
cd backend

# Create and activate a Python virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run the FastAPI server
uvicorn app.main:app --reload --port 8000
The backend API will be running at [http://127.0.0.1:8000](http://127.0.0.1:8000). Interactive API docs available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

2. Start the Frontend
Open a new PowerShell terminal (keep the backend running in the first one).

PowerShell
# Move into the frontend directory
cd frontend

# Install node modules (legacy-peer-deps handles React 18 strict peer resolutions)
npm install --legacy-peer-deps

# Start the Vite development server
npm run dev
The frontend dashboard will be available at http://localhost:5173.

🧪 Demonstration Mode
To evaluate the platform without uploading your own bank statements:

Create an account on the local frontend.

Click the "Load Synthetic Demo" button in the bottom-left sidebar.

The system will instantly populate a mathematically perfect 3-month financial history—including hidden subscriptions, silent price hikes, massive outliers, and regular salary deposits—so you can explore the analytics and health engine immediately.

🛡️ Security & Privacy Note
This repository includes a .env.example file. All cryptographic secrets (JWT keys) and database URLs must be injected via environment variables in production. The system includes an endpoint (/api/privacy/purge-data) allowing users to permanently wipe all financial traces from the database.
