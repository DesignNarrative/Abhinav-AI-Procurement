from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.schemas.rfq import (
    RFQCreate, RFQResponse, RFQDetailResponse,
    RFQStatusUpdate, RFQUpdate, RFQPreviewRequest,
    RFQItemCreate, RFQItemResponse,
    RFQVendorAdd, RFQVendorResponse
)
from app.services.rfq_service import RFQService

router = APIRouter(
    prefix="/rfqs",
    tags=["RFQ Management"]
)

# ──────────────────────────────────────────────────
# RFQ Core
# ──────────────────────────────────────────────────

@router.post("/", response_model=RFQResponse)
def create_rfq(
    data: RFQCreate,
    db: Session = Depends(get_db)
):
    return RFQService.create_rfq(db, data.model_dump())


@router.post(
    "/generate-from-requirement/{requirement_id}",
    response_model=RFQResponse
)
def generate_rfq_from_requirement(
    requirement_id: int,
    db: Session = Depends(get_db)
):
    """Generate a Draft RFQ by snapshotting an existing Requirement."""
    try:
        rfq = RFQService.generate_rfq_from_requirement(db, requirement_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not rfq:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return rfq


@router.get("/", response_model=list[RFQResponse])
def list_rfqs(
    status: str = None,
    db: Session = Depends(get_db)
):
    return RFQService.list_rfqs(db, status=status)


@router.get("/{rfq_id}", response_model=RFQDetailResponse)
def get_rfq(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    rfq = RFQService.get_rfq(db, rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfq


@router.put("/{rfq_id}/status")
def update_rfq_status(
    rfq_id: int,
    payload: RFQStatusUpdate,
    db: Session = Depends(get_db)
):
    rfq = RFQService.update_status(db, rfq_id, payload.status)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return {"rfq_id": rfq_id, "status": rfq.status}


@router.put("/{rfq_id}", response_model=RFQResponse)
def update_rfq(
    rfq_id: int,
    payload: RFQUpdate,
    db: Session = Depends(get_db)
):
    """Update RFQ-specific editable fields (payment terms)."""
    rfq = RFQService.update_rfq_details(
        db, rfq_id, payment_terms=payload.payment_terms
    )
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return rfq


# ──────────────────────────────────────────────────
# RFQ Items
# ──────────────────────────────────────────────────

@router.post("/{rfq_id}/items", response_model=RFQItemResponse)
def add_rfq_item(
    rfq_id: int,
    item: RFQItemCreate,
    db: Session = Depends(get_db)
):
    rfq = RFQService.get_rfq(db, rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return RFQService.add_item(db, rfq_id, item.model_dump())


@router.get("/{rfq_id}/items", response_model=list[RFQItemResponse])
def get_rfq_items(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    return RFQService.get_items(db, rfq_id)


# ──────────────────────────────────────────────────
# RFQ Vendors
# ──────────────────────────────────────────────────

@router.post("/{rfq_id}/vendors", response_model=RFQVendorResponse)
def add_rfq_vendor(
    rfq_id: int,
    payload: RFQVendorAdd,
    db: Session = Depends(get_db)
):
    rfq = RFQService.get_rfq(db, rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return RFQService.add_vendor(db, rfq_id, payload.vendor_id)


@router.get("/{rfq_id}/vendors", response_model=list[RFQVendorResponse])
def get_rfq_vendors(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    return RFQService.get_vendors(db, rfq_id)


# ──────────────────────────────────────────────────
# Send RFQ via WhatsApp
# ──────────────────────────────────────────────────

@router.post("/{rfq_id}/send")
def send_rfq(
    rfq_id: int,
    deadline: str = None,
    contact_person: str = None,
    contact_number: str = None,
    db: Session = Depends(get_db)
):
    rfq = RFQService.get_rfq(db, rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    result = RFQService.send_rfq_to_vendors(
        db, rfq_id,
        deadline=deadline,
        contact_person=contact_person,
        contact_number=contact_number
    )
    return result


# ──────────────────────────────────────────────────
# Preview WhatsApp Message (without sending)
# ──────────────────────────────────────────────────

@router.get("/{rfq_id}/preview")
def preview_rfq_message(
    rfq_id: int,
    deadline: str = None,
    contact_person: str = None,
    contact_number: str = None,
    db: Session = Depends(get_db)
):
    from app.services.rfq_whatsapp_service import generate_rfq_whatsapp_message
    from app.services.rfq_service import RFQService
    from app.models.rfq_item import RFQItem

    rfq = RFQService.get_rfq(db, rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    items = db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()
    item_dicts = [
        {
            "material_name": it.material_name,
            "material_category": it.material_category,
            "quantity": float(it.quantity),
            "unit": it.unit,
            "brand_required": it.brand_required,
            "dynamic_fields": it.dynamic_fields or {},
            "remarks": it.remarks
        }
        for it in items
    ]

    message = generate_rfq_whatsapp_message(
        rfq_number=rfq.rfq_number,
        project_name=rfq.project_name,
        site_name=rfq.site_name,
        delivery_location=rfq.delivery_location,
        payment_terms=rfq.payment_terms,
        items=item_dicts,
        deadline=deadline,
        contact_person=contact_person,
        contact_number=contact_number,
        priority=rfq.priority,
        required_date=rfq.required_date,
        purpose=rfq.purpose
    )

    return {"rfq_number": rfq.rfq_number, "message": message}


# ─────────────────────────────────────
# Preview WhatsApp Message BEFORE saving (unified create page)
# ─────────────────────────────────────

@router.post("/preview")
def preview_rfq_message_unsaved(
    payload: RFQPreviewRequest
):
    """Build the WhatsApp message from a draft form payload (no DB write).

    Uses the SAME generator as send/details preview so the message shown is
    exactly what will be sent.
    """
    from app.services.rfq_whatsapp_service import generate_rfq_whatsapp_message

    item_dicts = [
        {
            "material_name": it.material_name,
            "material_category": it.material_category,
            "quantity": it.quantity,
            "unit": it.unit,
            "brand_required": it.brand_required,
            "dynamic_fields": it.dynamic_fields or {},
            "remarks": it.remarks
        }
        for it in payload.items
    ]

    message = generate_rfq_whatsapp_message(
        rfq_number="RFQ-PREVIEW",
        project_name=payload.project_name,
        site_name=payload.site_name,
        delivery_location=payload.delivery_location,
        payment_terms=payload.payment_terms,
        items=item_dicts,
        deadline=payload.deadline,
        contact_person=payload.contact_person,
        contact_number=payload.contact_number,
        priority=payload.priority,
        required_date=payload.required_date,
        purpose=payload.purpose
    )

    return {"message": message}
