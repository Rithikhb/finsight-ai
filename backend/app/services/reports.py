import io
from datetime import datetime
from typing import List, Dict, Any
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from ..models import Transaction, User


def generate_csv_report(txns: List[Transaction]) -> bytes:
    rows = [{
        "Date": t.txn_date.isoformat(),
        "Merchant": t.merchant,
        "Description": t.description,
        "Category": t.category,
        "Type": t.txn_type,
        "Debit": float(t.debit),
        "Credit": float(t.credit),
        "Signed_Amount": float(t.signed_amount),
        "Balance": float(t.balance) if t.balance is not None else "",
        "Currency": t.currency,
        "Confidence": float(t.categorization_confidence),
        "Unusual_Flag": t.is_unusual,
        "Review_Status": t.review_status,
        "Synthetic_Demo": t.is_synthetic
    } for t in txns]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def generate_excel_report(txns: List[Transaction], summary: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary_df = pd.DataFrame([
            {"Metric": "Reporting Period", "Value": summary.get("period", "All")},
            {"Metric": "Total Income", "Value": summary.get("total_income", 0.0)},
            {"Metric": "Total Net Expenses", "Value": summary.get("total_expenses", 0.0)},
            {"Metric": "Net Cash Flow", "Value": summary.get("net_cash_flow", 0.0)},
            {"Metric": "Savings Rate (%)", "Value": summary.get("savings_rate", 0.0)},
            {"Metric": "Financial Health Score", "Value": summary.get("health_score", "N/A")},
            {"Metric": "Generated Timestamp (UTC)", "Value": datetime.utcnow().isoformat()},
        ])
        summary_df.to_excel(writer, index=False, sheet_name="Financial_Summary")

        txn_rows = [{
            "Date": t.txn_date.isoformat(),
            "Merchant": t.merchant,
            "Description": t.description,
            "Category": t.category,
            "Type": t.txn_type,
            "Debit": float(t.debit),
            "Credit": float(t.credit),
            "Balance": float(t.balance) if t.balance is not None else None,
            "Review_Status": t.review_status
        } for t in txns]
        pd.DataFrame(txn_rows).to_excel(writer, index=False, sheet_name="Transactions")
    return buf.getvalue()


def generate_pdf_report(user: User, txns: List[Transaction], summary: Dict[str, Any], health: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>FinSight AI — Financial Health & Intelligence Report</b>", styles["Title"]))
    story.append(Paragraph(
        f"Prepared for: {user.name} | Currency: {user.currency} | Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"]
    ))
    story.append(Paragraph(f"Reporting Period: {health.get('data_period', 'All Available Data')}", styles["Normal"]))
    story.append(Spacer(1, 14))

    # Executive Summary Table
    cur = user.currency
    sum_data = [
        ["Metric", "Value", "Indicator Note"],
        ["Total Verified Income", f"{cur} {summary['total_income']:,.2f}", "Excludes internal self-transfers"],
        ["Total Net Expenses", f"{cur} {summary['total_expenses']:,.2f}", "Net of verified refunds"],
        ["Net Cash Flow", f"{cur} {summary['net_cash_flow']:,.2f}", "Income minus Net Expenses"],
        ["Savings Rate", f"{summary['savings_rate']:.1f}%", "Target >= 20%"],
        ["Financial Health Score", f"{health.get('overall_score', 'N/A')} / 100", health.get("status", "N/A")],
    ]
    t1 = Table(sum_data, colWidths=[160, 130, 210])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t1)
    story.append(Spacer(1, 14))

    story.append(Paragraph("<b>Financial Health Component Breakdown</b>", styles["Heading3"]))
    comp_rows = [["Component", "Weight", "Observed Value", "Score (0-100)"]]
    for c in health.get("components", []):
        comp_rows.append([
            c["name"],
            f"{int(c['weight'] * 100)}%",
            str(c["raw_metric"]),
            str(c["normalized_score"]) if c["normalized_score"] is not None else "Excluded"
        ])
    t2 = Table(comp_rows, colWidths=[170, 60, 170, 100])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D9488")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t2)
    story.append(Spacer(1, 14))

    story.append(Paragraph("<b>Recent Transactions Sample (Top 15)</b>", styles["Heading3"]))
    txn_rows = [["Date", "Merchant", "Category", "Amount", "Status"]]
    for t in txns[:15]:
        txn_rows.append([
            t.txn_date.isoformat(),
            t.merchant[:24],
            t.category[:20],
            f"{cur} {float(t.signed_amount):,.2f}",
            "Flagged" if t.is_unusual else "Verified"
        ])
    t3 = Table(txn_rows, colWidths=[75, 135, 120, 95, 75])
    t3.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t3)

    doc.build(story)
    return buf.getvalue()