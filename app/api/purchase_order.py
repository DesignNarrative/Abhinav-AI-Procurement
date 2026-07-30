from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier import Supplier
from app.schemas.purchase_order import (
    POCreateFromAward,
    POUpdate,
    POStatusUpdate,
    POResponse
)
from app.services.purchase_order_service import PurchaseOrderService

router = APIRouter(tags=["Purchase Orders"])

templates = Jinja2Templates(directory="app/templates")


# =====================================================
# JSON API
# =====================================================

@router.post("/purchase-orders/from-award")
def create_po_from_award(
    payload: POCreateFromAward,
    db: Session = Depends(get_db)
):
    try:
        po = PurchaseOrderService.create_from_award(
            db=db,
            rfq_id=payload.rfq_id,
            created_by=payload.created_by
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return POResponse.model_validate(po)


@router.put("/purchase-orders/{po_id}")
def update_po(
    po_id: int,
    payload: POUpdate,
    db: Session = Depends(get_db)
):
    try:
        po = PurchaseOrderService.update_po(
            db, po_id, payload.model_dump(exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return POResponse.model_validate(po)


@router.put("/purchase-orders/{po_id}/status")
def update_po_status(
    po_id: int,
    payload: POStatusUpdate,
    db: Session = Depends(get_db)
):
    try:
        po = PurchaseOrderService.update_status(
            db, po_id, payload.status, payload.approved_by
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return POResponse.model_validate(po)


@router.post("/purchase-orders/{po_id}/generate-pdf")
def generate_po_pdf(po_id: int, db: Session = Depends(get_db)):
    try:
        path = PurchaseOrderService.generate_pdf(db, po_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"pdf_path": "/" + path}


@router.post("/purchase-orders/{po_id}/send")
def send_po(po_id: int, db: Session = Depends(get_db)):
    try:
        result = PurchaseOrderService.send_to_vendor(db, po_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# =====================================================
# HTML Dashboard
# =====================================================

@router.get("/dashboard/purchase-orders", response_class=HTMLResponse)
def po_list_page(request: Request, db: Session = Depends(get_db)):
    pos = PurchaseOrderService.list_pos(db)
    # Attach vendor names for display
    rows = []
    for po in pos:
        vendor = db.query(Supplier).filter(
            Supplier.id == po.vendor_id
        ).first()
        rows.append({
            "po": po,
            "vendor_name": vendor.company_name if vendor else "-"
        })
    return templates.TemplateResponse(
        request=request,
        name="po_management.html",
        context={"request": request, "rows": rows}
    )


@router.get(
    "/dashboard/purchase-orders/{po_id}",
    response_class=HTMLResponse
)
def po_details_page(
    po_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    po = PurchaseOrderService.get_po(db, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    items = db.query(PurchaseOrderItem).filter(
        PurchaseOrderItem.po_id == po_id
    ).order_by(PurchaseOrderItem.id.asc()).all()

    vendor = db.query(Supplier).filter(
        Supplier.id == po.vendor_id
    ).first()

    return templates.TemplateResponse(
        request=request,
        name="po_details.html",
        context={
            "request": request,
            "po": po,
            "items": items,
            "vendor": vendor
        }
    )
