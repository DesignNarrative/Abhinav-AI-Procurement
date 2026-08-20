from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.schemas.comparison import (
    ScoringWeightsUpdate, AwardCreate, AwardResponse
)
from app.services.comparison_service import ComparisonService

router = APIRouter(
    tags=["Quotation Comparison & Award"]
)


# ──────────────────────────────────────────────────
# Comparison Matrix
# ──────────────────────────────────────────────────

@router.get("/rfqs/{rfq_id}/comparison")
def get_comparison(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    """
    Side-by-side comparison of all latest quotations for an RFQ:
    per-item landed rates with L1/L2/L3 ranking, weighted scores
    and an advisory AI recommendation.
    """
    result = ComparisonService.build_comparison(db, rfq_id)
    if result is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return result


# ──────────────────────────────────────────────────
# Award (final vendor selection)
# ──────────────────────────────────────────────────

@router.post(
    "/rfqs/{rfq_id}/award",
    response_model=AwardResponse
)
def create_award(
    rfq_id: int,
    payload: AwardCreate,
    db: Session = Depends(get_db)
):
    """
    Record the final vendor selection for an RFQ.
    Marks the winning quotation as 'Selected' and the RFQ as 'Awarded'.
    """
    try:
        return ComparisonService.create_award(
            db=db,
            rfq_id=rfq_id,
            quotation_id=payload.quotation_id,
            selection_reason=payload.selection_reason,
            approved_by=payload.approved_by,
            remarks=payload.remarks
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/rfqs/{rfq_id}/award",
    response_model=AwardResponse
)
def get_award(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    award = ComparisonService.get_award(db, rfq_id)
    if not award:
        raise HTTPException(
            status_code=404,
            detail="No award recorded for this RFQ."
        )
    return award


# ──────────────────────────────────────────────────
# Scoring Config
# ──────────────────────────────────────────────────

@router.get("/scoring-config")
def get_scoring_weights(
    db: Session = Depends(get_db)
):
    return {"weights": ComparisonService.get_weights(db)}


@router.put("/scoring-config")
def update_scoring_weights(
    payload: ScoringWeightsUpdate,
    db: Session = Depends(get_db)
):
    try:
        weights = ComparisonService.update_weights(db, payload.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"weights": weights}


# ──────────────────────────────────────────────────
# Award + Create PO + Send WhatsApp Notifications
# ──────────────────────────────────────────────────

from fastapi import Body
from pydantic import BaseModel
from typing import Optional as _Optional


class AwardAndNotifyPayload(BaseModel):
    rfq_id: int
    winning_vendor_id: int
    winning_quotation_id: int
    selection_reason: _Optional[str] = None
    approved_by: _Optional[str] = "Purchase Manager"
    remarks: _Optional[str] = None


@router.post("/rfqs/{rfq_id}/award-and-notify")
def award_and_notify(
    rfq_id: int,
    payload: AwardAndNotifyPayload,
    db: Session = Depends(get_db)
):
    """
    Complete award flow:
    1. Record award (winning quotation)
    2. Create Purchase Order
    3. Send WhatsApp approval msg to winner
    4. Send WhatsApp consolation msg to all other vendors who submitted quotations
    5. Mark RFQ as Closed, Requirement as COMPLETED
    Returns: { po_id, po_number, messages_sent: { winner: bool, consolation: [{ vendor_id, sent }] } }
    """
    from app.models.rfq import RFQ
    from app.models.rfq_vendor import RFQVendor
    from app.models.quotation import Quotation
    from app.models.supplier import Supplier
    from app.models.requirement import Requirement
    from app.services.purchase_order_service import PurchaseOrderService
    from app.services.rfq_whatsapp_service import send_award_winner_message, send_award_consolation_message

    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    # Step 1: Record award
    try:
        ComparisonService.create_award(
            db=db,
            rfq_id=rfq_id,
            quotation_id=payload.winning_quotation_id,
            selection_reason=payload.selection_reason or "Best overall quotation",
            approved_by=payload.approved_by or "Purchase Manager",
            remarks=payload.remarks
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Step 2: Create Purchase Order
    try:
        po = PurchaseOrderService.create_from_award(
            db=db,
            rfq_id=rfq_id,
            created_by=payload.approved_by or "Purchase Manager"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PO creation failed: {str(e)}")

    # Step 3: Send winner message
    winner_vendor = db.query(Supplier).filter(Supplier.id == payload.winning_vendor_id).first()
    winner_sent = False
    if winner_vendor:
        winner_sent = send_award_winner_message(winner_vendor, rfq, po)

    # Step 4: Send consolation messages to all OTHER vendors who submitted quotations
    consolation_results = []
    all_rfq_vendors = db.query(RFQVendor).filter(RFQVendor.rfq_id == rfq_id).all()
    for rv in all_rfq_vendors:
        if rv.vendor_id == payload.winning_vendor_id:
            continue  # skip winner
        # Only message vendors who actually submitted a quotation
        submitted = db.query(Quotation).filter(
            Quotation.rfq_id == rfq_id,
            Quotation.vendor_id == rv.vendor_id
        ).first()
        if not submitted:
            consolation_results.append({"vendor_id": rv.vendor_id, "sent": False, "reason": "No quotation submitted"})
            continue
        vendor = db.query(Supplier).filter(Supplier.id == rv.vendor_id).first()
        if vendor:
            sent = send_award_consolation_message(vendor, rfq)
            consolation_results.append({"vendor_id": rv.vendor_id, "vendor_name": vendor.company_name, "sent": sent})

    # Step 5: Mark RFQ as Closed
    rfq.status = "Closed"
    db.commit()

    # Mark Requirement as COMPLETED if linked
    if rfq.requirement_id:
        req = db.query(Requirement).filter(Requirement.id == rfq.requirement_id).first()
        if req:
            req.status = "COMPLETED"
            db.commit()

    return {
        "success": True,
        "po_id": po.id,
        "po_number": po.po_number,
        "messages_sent": {
            "winner": winner_sent,
            "consolation": consolation_results
        }
    }
