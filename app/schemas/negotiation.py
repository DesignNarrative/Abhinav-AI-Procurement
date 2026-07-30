from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# =====================================================
# Create a negotiation round
# =====================================================

class NegotiationCreate(BaseModel):
    vendor_id: int
    quotation_id: Optional[int] = None

    # WhatsApp, Call, Email, In Person
    channel: str = "Call"

    original_price: Optional[float] = None
    counter_price: Optional[float] = None
    agreed_price: Optional[float] = None

    summary: Optional[str] = None

    # Pending, Agreed, Rejected, Revised Quotation Expected
    outcome: str = "Pending"

    created_by: str

    # Optionally push the counter offer to the vendor on WhatsApp
    send_whatsapp: bool = False
    whatsapp_message: Optional[str] = None


# =====================================================
# Response
# =====================================================

class NegotiationResponse(BaseModel):
    id: int
    rfq_id: int
    vendor_id: int
    quotation_id: Optional[int] = None
    round_number: int
    channel: str
    original_price: Optional[float] = None
    counter_price: Optional[float] = None
    agreed_price: Optional[float] = None
    summary: Optional[str] = None
    outcome: str
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True
