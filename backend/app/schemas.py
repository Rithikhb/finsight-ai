from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from decimal import Decimal


class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    currency: str = "INR"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    currency: str
    locale: str
    monthly_total_budget: float

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AccountCreate(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=120)
    account_type: str = "Savings"
    currency: str = "INR"
    masked_identifier: Optional[str] = None


class AccountOut(BaseModel):
    id: int
    display_name: str
    account_type: str
    currency: str
    masked_identifier: Optional[str]
    is_demo: bool

    class Config:
        from_attributes = True


class ParsedRowPreview(BaseModel):
    temp_id: int
    txn_date: Optional[str]
    raw_date: str
    description: str
    merchant: str
    debit: float
    credit: float
    signed_amount: float
    balance: Optional[float]
    category: str
    txn_type: str
    extraction_confidence: float
    categorization_confidence: float
    classification_source: str
    validation_errors: List[str]
    is_duplicate_candidate: bool
    duplicate_reason: Optional[str] = None
    include_in_import: bool = True


class UploadPreviewResponse(BaseModel):
    filename: str
    account_id: int
    total_rows_discovered: int
    valid_rows_count: int
    rows_requiring_correction: int
    duplicate_candidates_count: int
    reconciliation_status: str
    reconciliation_details: str
    rows: List[ParsedRowPreview]


class ConfirmImportRequest(BaseModel):
    account_id: int
    filename: str
    reconciliation_status: str
    reconciliation_details: str
    rows: List[ParsedRowPreview]


class TransactionUpdate(BaseModel):
    merchant: Optional[str] = None
    category: Optional[str] = None
    txn_type: Optional[str] = None
    review_status: Optional[str] = None
    exclude_from_analytics: Optional[bool] = None
    apply_rule_to_similar: bool = False


class BudgetUpsert(BaseModel):
    category: str
    target_amount: float = Field(..., ge=0)
    alert_threshold_pct: int = Field(85, ge=10, le=100)


class TotalBudgetUpdate(BaseModel):
    monthly_total_budget: float = Field(..., ge=0)


class RecurringStatusUpdate(BaseModel):
    review_status: str  # USEFUL, UNWANTED, INCORRECT, REVIEWED


class AnomalyActionUpdate(BaseModel):
    review_status: str  # REVIEWED, EXPECTED, INVESTIGATE, DISMISSED
    corrected_category: Optional[str] = None


class AssistantQuery(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    use_local_llm: bool = False