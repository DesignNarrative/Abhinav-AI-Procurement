from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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


class RFQResendPayload(BaseModel):
    vendor_ids: list[int]
    deadline: Optional[str] = None
    contact_person: Optional[str] = None
    contact_number: Optional[str] = None


@router.post("/{rfq_id}/resend")
def resend_rfq(
    rfq_id: int,
    payload: RFQResendPayload,
    db: Session = Depends(get_db)
):
    """
    Re-send (or first-send) the RFQ to a specific subset of vendors.
    Accepts a list of vendor_ids.  Each vendor is added to the RFQ if not
    already attached, then the WhatsApp message is delivered.
    Works regardless of RFQ status (Draft or Sent).
    """
    rfq = RFQService.get_rfq(db, rfq_id)
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    result = RFQService.resend_rfq_to_specific_vendors(
        db, rfq_id,
        vendor_ids=payload.vendor_ids,
        deadline=payload.deadline,
        contact_person=payload.contact_person,
        contact_number=payload.contact_number
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


# ──────────────────────────────────────────────────────────────
# Online Supplier Discovery Routes
# ──────────────────────────────────────────────────────────────

from pydantic import BaseModel
from app.services.supplier_discovery_service import discover_online_suppliers
from app.models.rfq_vendor import RFQVendor
from app.services.rfq_whatsapp_service import generate_rfq_whatsapp_message
from app.services.whatsapp_service import send_text_message
from sqlalchemy import text

class DiscoveredSupplierItem(BaseModel):
    company_name: str
    whatsapp_number: str
    material: str

class AddDiscoveredSuppliersRequest(BaseModel):
    suppliers: list[DiscoveredSupplierItem]
    deadline: Optional[str] = None
    contact_person: Optional[str] = None
    contact_number: Optional[str] = None


@router.get("/{rfq_id}/discover-suppliers")
def get_discovered_suppliers(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    """
    Search online (or simulate search) for matching local suppliers for this RFQ's materials.
    """
    try:
        results = discover_online_suppliers(db, rfq_id)
        return {"status": "success", "suppliers": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{rfq_id}/add-discovered-suppliers")
def add_discovered_suppliers(
    rfq_id: int,
    payload: AddDiscoveredSuppliersRequest,
    db: Session = Depends(get_db)
):
    """
    Create Supplier records for selected online vendors, link them to the RFQ, and dispatch the WhatsApp RFQ template.
    """
    from app.models.rfq import RFQ
    from app.models.supplier import Supplier

    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    from app.models.rfq_item import RFQItem
    items = db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()
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
        for it in items
    ]

    # Generate custom RFQ message
    rfq_message = generate_rfq_whatsapp_message(
        rfq_number=rfq.rfq_number,
        project_name=rfq.project_name,
        site_name=rfq.site_name,
        delivery_location=rfq.delivery_location,
        payment_terms=rfq.payment_terms,
        items=item_dicts,
        deadline=payload.deadline,
        contact_person=payload.contact_person,
        contact_number=payload.contact_number,
        priority=rfq.priority,
        required_date=rfq.required_date,
        purpose=rfq.purpose
    )

    added_count = 0
    for s_info in payload.suppliers:
        # Check if number already registered
        from app.services.whatsapp_service import normalize_phone_number
        norm_phone = normalize_phone_number(s_info.whatsapp_number)
        clean_phone_10 = norm_phone[-10:]

        supplier = db.query(Supplier).filter(
            (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
            (Supplier.whatsapp_number == norm_phone)
        ).first()

        if not supplier:
            # Create a new auto-approved supplier
            from app.api.supplier import generate_next_supplier_code
            supplier_code = generate_next_supplier_code(db)

            supplier = Supplier(
                supplier_code=supplier_code,
                company_name=s_info.company_name,
                contact_person_name=s_info.company_name,
                whatsapp_number=norm_phone,
                registration_status="PENDING_REGISTRATION",
                declaration_accepted=False,
                supplier_category=s_info.material,
                registered_address="Pending Registration",
                bank_name="Pending Registration",
                beneficiary_name="Pending Registration",
                bank_account_number="Pending Registration",
                bank_ifsc="Pending Registration"
            )
            db.add(supplier)
            db.flush()

        # Link to RFQ if not already linked
        link = db.query(RFQVendor).filter(
            RFQVendor.rfq_id == rfq_id,
            RFQVendor.vendor_id == supplier.id
        ).first()

        if not link:
            link = RFQVendor(
                rfq_id=rfq_id,
                vendor_id=supplier.id,
                whatsapp_status="Sent"
            )
            db.add(link)
            db.flush()

        # Dispatch the WhatsApp message
        try:
            send_text_message(supplier.whatsapp_number, rfq_message)
            link.whatsapp_status = "Sent"
            added_count += 1
        except Exception as send_err:
            print(f"[DISCOVERY] Failed to send to {supplier.whatsapp_number}: {send_err}")
            link.whatsapp_status = "Failed"

    db.commit()
    return {"status": "success", "notified_count": added_count}

