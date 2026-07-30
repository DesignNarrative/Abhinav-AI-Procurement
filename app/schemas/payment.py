from pydantic import BaseModel
from typing import Optional
from datetime import date


# =====================================================
# Create a payment (scheduled or recorded)
# =====================================================

class PaymentCreate(BaseModel):
    invoice_id: int
    payment_type: str = "Full"
    amount: float = 0.0
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    reference: Optional[str] = None
    status: str = "Pending"
    remarks: Optional[str] = None
    created_by: str


# =====================================================
# Mark a payment as paid
# =====================================================

class PaymentMarkPaid(BaseModel):
    paid_date: Optional[date] = None
    reference: Optional[str] = None
