from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime


# =====================================================
# Create PO from an awarded RFQ
# =====================================================

class POCreateFromAward(BaseModel):
    rfq_id: int
    created_by: str


# =====================================================
# Update PO header (Draft only)
# =====================================================

class POUpdate(BaseModel):
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    site_name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_number: Optional[str] = None
    payment_terms: Optional[str] = None
    delivery_timeline: Optional[str] = None
    penalty_terms: Optional[str] = None
    terms_conditions: Optional[str] = None


class POStatusUpdate(BaseModel):
    status: str
    approved_by: Optional[str] = None


# =====================================================
# Responses
# =====================================================

class POItemResponse(BaseModel):
    id: int
    material_category: Optional[str] = None
    material_name: str
    ordered_quantity: float
    unit: str
    brand: Optional[str] = None
    basic_rate: float
    discount_percent: float
    tax_percent: float
    freight_amount: float
    final_landed_rate: float
    total_amount: float
    remarks: Optional[str] = None

    class Config:
        from_attributes = True


class POResponse(BaseModel):
    id: int
    po_number: str
    award_id: Optional[int] = None
    rfq_id: Optional[int] = None
    quotation_id: Optional[int] = None
    vendor_id: int
    po_date: Optional[date] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    site_name: Optional[str] = None
    contact_person: Optional[str] = None
    contact_number: Optional[str] = None
    payment_terms: Optional[str] = None
    delivery_timeline: Optional[str] = None
    penalty_terms: Optional[str] = None
    terms_conditions: Optional[str] = None
    freight_total: float
    loading_unloading_total: float
    grand_total: float
    status: str
    pdf_path: Optional[str] = None
    whatsapp_status: Optional[str] = None
    approved_by: Optional[str] = None
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True
