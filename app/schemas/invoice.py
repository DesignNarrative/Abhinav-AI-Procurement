from pydantic import BaseModel
from typing import Optional, List
from datetime import date


# =====================================================
# Invoice line item
# =====================================================

class InvoiceItemCreate(BaseModel):
    po_item_id: Optional[int] = None
    material_name: str
    unit: Optional[str] = None
    invoiced_quantity: float = 0.0
    rate: float = 0.0
    tax_percent: float = 0.0
    amount: float = 0.0
    remarks: Optional[str] = None


# =====================================================
# Create an invoice
# =====================================================

class InvoiceCreate(BaseModel):
    vendor_id: int
    po_id: Optional[int] = None
    document_uuid: Optional[str] = None
    invoice_number: str
    invoice_date: Optional[date] = None
    taxable_amount: float = 0.0
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    total_tax_amount: float = 0.0
    freight_amount: float = 0.0
    invoice_amount: float = 0.0
    file_path: Optional[str] = None
    created_by: str
    items: List[InvoiceItemCreate] = []


# =====================================================
# Status update
# =====================================================

class InvoiceStatusUpdate(BaseModel):
    status: str
    approved_by: Optional[str] = None
