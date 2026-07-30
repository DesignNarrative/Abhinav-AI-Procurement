from pydantic import BaseModel
from typing import Optional, List
from datetime import date


# =====================================================
# Create a delivery (dispatch)
# =====================================================

class DeliveryCreate(BaseModel):
    dispatch_date: Optional[date] = None
    eta: Optional[date] = None
    vehicle_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_number: Optional[str] = None
    lr_copy_path: Optional[str] = None
    status: str = "Dispatched"
    remarks: Optional[str] = None
    created_by: str


# =====================================================
# GRN confirmation
# =====================================================

class GRNItem(BaseModel):
    po_item_id: int
    received_quantity: float = 0.0
    quality_ok: bool = True
    damage_notes: Optional[str] = None
    photo_path: Optional[str] = None


class GRNRecord(BaseModel):
    confirmed_by: str
    items: List[GRNItem]
