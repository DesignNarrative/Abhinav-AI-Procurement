from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.supplier import Supplier

router = APIRouter(
    prefix="/dashboard/quotation",
    tags=["Quotation Dashboard"]
)

templates = Jinja2Templates(directory="app/templates")

@router.get("/create", response_class=HTMLResponse)
def quotation_create_form(
    rfq_id: int,
    vendor_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
        
    vendor = db.query(Supplier).filter(Supplier.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    rfq_items = db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()
    
    # Check if there's an existing quotation to show revision context
    existing = db.query(Quotation).filter(
        Quotation.rfq_id == rfq_id,
        Quotation.vendor_id == vendor_id
    ).order_by(Quotation.revision_number.desc()).first()

    return templates.TemplateResponse(
        request=request,
        name="quotation_create.html",
        context={
            "request": request,
            "rfq": rfq,
            "vendor": vendor,
            "rfq_items": rfq_items,
            "existing_quotation": existing
        }
    )

@router.get("/{quotation_id}", response_class=HTMLResponse)
def quotation_details(
    quotation_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    items = db.query(QuotationItem).filter(QuotationItem.quotation_id == quotation_id).all()
    rfq = db.query(RFQ).filter(RFQ.id == quotation.rfq_id).first()
    vendor = db.query(Supplier).filter(Supplier.id == quotation.vendor_id).first()
    
    # Enrich items with RFQ item context
    enriched_items = []
    for item in items:
        r_item = db.query(RFQItem).filter(RFQItem.id == item.rfq_item_id).first()
        enriched_items.append({
            "quote_item": item,
            "rfq_item": r_item
        })

    return templates.TemplateResponse(
        request=request,
        name="quotation_details.html",
        context={
            "request": request,
            "quotation": quotation,
            "enriched_items": enriched_items,
            "rfq": rfq,
            "vendor": vendor
        }
    )


from fastapi import Body
from typing import Optional as _Optional
from pydantic import BaseModel as _BaseModel


class QuotationEditPayload(_BaseModel):
    payment_terms: _Optional[str] = None
    delivery_timeline: _Optional[str] = None
    grand_total: _Optional[float] = None
    freight_amount_total: _Optional[float] = None
    loading_unloading_total: _Optional[float] = None


@router.put("/{quotation_id}/edit")
def edit_quotation(
    quotation_id: int,
    payload: QuotationEditPayload,
    db: Session = Depends(get_db)
):
    """Edit quotation header fields from dashboard."""
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")

    if payload.payment_terms is not None:
        quotation.payment_terms = payload.payment_terms
    if payload.delivery_timeline is not None:
        quotation.delivery_timeline = payload.delivery_timeline
    if payload.grand_total is not None:
        quotation.grand_total = payload.grand_total
    if payload.freight_amount_total is not None:
        quotation.freight_amount_total = payload.freight_amount_total
    if payload.loading_unloading_total is not None:
        quotation.loading_unloading_total = payload.loading_unloading_total

    db.commit()
    db.refresh(quotation)
    return {"success": True, "quotation_id": quotation.id}
