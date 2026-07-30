from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.schemas.delivery import DeliveryCreate, GRNRecord
from app.services.delivery_service import DeliveryService

router = APIRouter(tags=["Delivery & GRN"])


# =====================================================
# Deliveries for a PO
# =====================================================

@router.post("/purchase-orders/{po_id}/deliveries")
def create_delivery(
    po_id: int,
    payload: DeliveryCreate,
    db: Session = Depends(get_db)
):
    try:
        delivery = DeliveryService.create_delivery(
            db, po_id, payload.model_dump()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": delivery.id, "status": delivery.status}


@router.get("/purchase-orders/{po_id}/deliveries")
def list_deliveries(po_id: int, db: Session = Depends(get_db)):
    return {
        "po_id": po_id,
        "deliveries": DeliveryService.list_deliveries(db, po_id),
        "receipt_summary": DeliveryService.get_po_receipt_summary(db, po_id)
    }


@router.get("/purchase-orders/{po_id}/receipt-summary")
def receipt_summary(po_id: int, db: Session = Depends(get_db)):
    return {
        "po_id": po_id,
        "receipt_summary": DeliveryService.get_po_receipt_summary(db, po_id)
    }


# =====================================================
# GRN confirmation for a delivery
# =====================================================

@router.post("/deliveries/{delivery_id}/grn")
def record_grn(
    delivery_id: int,
    payload: GRNRecord,
    db: Session = Depends(get_db)
):
    try:
        delivery = DeliveryService.record_grn(
            db=db,
            delivery_id=delivery_id,
            confirmed_by=payload.confirmed_by,
            items=[item.model_dump() for item in payload.items]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "id": delivery.id,
        "status": delivery.status,
        "confirmed_by": delivery.confirmed_by
    }
