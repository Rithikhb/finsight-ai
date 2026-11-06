import io
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db

SQLALCHEMY_TEST_URL = "sqlite:///./test_finsight.db"
engine_test = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def setup_module(module):
    Base.metadata.drop_all(bind=engine_test)
    Base.metadata.create_all(bind=engine_test)


def register_and_get_headers(email: str, name: str = "Test User"):
    res = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": "StrongPassword123!", "currency": "INR"
    })
    assert res.status_code == 201
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_1_csv_upload_reconciliation_and_duplicates():
    headers = register_and_get_headers("alice@example.com", "Alice")
    accs = client.get("/api/accounts", headers=headers).json()
    acc_id = accs[0]["id"]

    csv_content = (
        "Date,Description,Debit,Credit,Balance\n"
        "2026-10-01,NEFT CR SALARY OCT,0.00,50000.00,60000.00\n"
        "2026-10-02,UPI/SWIGGY FOOD ORDER,500.00,0.00,59500.00\n"
        "2026-10-02,UPI/SWIGGY FOOD ORDER,500.00,0.00,59000.00\n"  # Same-file duplicate candidate
    )
    res = client.post(
        "/api/statements/upload-preview",
        headers=headers,
        data={"account_id": str(acc_id)},
        files={"file": ("oct.csv", csv_content.encode("utf-8"), "text/csv")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_rows_discovered"] == 3
    assert data["reconciliation_status"] == "VERIFIED"
    assert data["duplicate_candidates_count"] == 1


def test_2_balance_discrepancy_detection():
    headers = register_and_get_headers("bob@example.com", "Bob")
    acc_id = client.get("/api/accounts", headers=headers).json()[0]["id"]

    # Intentional balance error on row 2 (60000 - 500 != 55000)
    bad_csv = (
        "Date,Description,Debit,Credit,Balance\n"
        "2026-10-01,NEFT CR SALARY,0.00,50000.00,60000.00\n"
        "2026-10-03,UPI/BLINKIT GROCERY,500.00,0.00,55000.00\n"
    )
    res = client.post(
        "/api/statements/upload-preview",
        headers=headers,
        data={"account_id": str(acc_id)},
        files={"file": ("bad_bal.csv", bad_csv.encode("utf-8"), "text/csv")}
    )
    assert res.status_code == 200
    assert res.json()["reconciliation_status"] == "DISCREPANCY_DETECTED"


def test_3_demo_workflow_recurring_anomalies_and_health_score():
    headers = register_and_get_headers("charlie@example.com", "Charlie")
    demo_res = client.post("/api/demo/load", headers=headers)
    assert demo_res.status_code == 200
    stats = demo_res.json()["stats"]
    assert stats["transactions_seeded"] > 30
    assert stats["recurring_detected"] >= 5
    assert stats["anomalies_flagged"] >= 2

    # Check transfer & refund handling in overview
    ov = client.get("/api/analytics/overview", headers=headers).json()
    cards = ov["summary_cards"]
    assert cards["total_transfers_excluded"] == 10000.0
    assert cards["total_refunds"] == 850.0

    # Check Financial Health Score formula & range
    health = client.get("/api/financial-health", headers=headers).json()
    assert 0 <= health["overall_score"] <= 100
    assert len(health["components"]) == 5

    # Check Grounded Assistant
    ans = client.post("/api/assistant/query", headers=headers, json={
        "question": "What recurring payments were detected?", "use_local_llm": False
    }).json()
    assert "recurring" in ans["answer"].lower()


def test_4_zero_income_missing_data_policy():
    headers = register_and_get_headers("noincome@example.com", "NoIncome")
    acc_id = client.get("/api/accounts", headers=headers).json()[0]["id"]

    # Upload only expenses (0 income)
    csv_exp = (
        "Date,Description,Debit,Credit,Balance\n"
        "2026-09-10,UPI/DMART GROCERY,1200.00,0.00,8800.00\n"
        "2026-10-10,UPI/DMART GROCERY,1300.00,0.00,7500.00\n"
    )
    prev = client.post(
        "/api/statements/upload-preview",
        headers=headers,
        data={"account_id": str(acc_id)},
        files={"file": ("exp.csv", csv_exp.encode("utf-8"), "text/csv")}
    ).json()
    client.post("/api/statements/confirm-import", headers=headers, json=prev)

    health = client.get("/api/financial-health", headers=headers).json()
    assert "RENORMALIZED_WEIGHTS_POLICY" in health["policy_applied"]
    savings_comp = [c for c in health["components"] if c["key"] == "savings_rate"][0]
    assert savings_comp["available"] is False


def test_5_strict_user_isolation_and_deletion():
    h1 = register_and_get_headers("user1@isolated.com", "User1")
    h2 = register_and_get_headers("user2@isolated.com", "User2")

    client.post("/api/demo/load", headers=h1)
    u1_txns = client.get("/api/transactions", headers=h1).json()
    u2_txns = client.get("/api/transactions", headers=h2).json()
    assert len(u1_txns) > 30
    assert len(u2_txns) == 0  # User 2 must never see User 1's transactions

    # User 2 attempting to modify User 1's transaction must fail with 404
    hack_res = client.patch(f"/api/transactions/{u1_txns[0]['id']}", headers=h2, json={"category": "Shopping"})
    assert hack_res.status_code == 404

    # Purge data test
    purge_res = client.delete("/api/privacy/purge-data", headers=h1)
    assert purge_res.status_code == 200
    assert len(client.get("/api/transactions", headers=h1).json()) == 0