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
from typing import Optional as _Optional, List as _List
from pydantic import BaseModel as _BaseModel


class QuotationEditPayload(_BaseModel):
    payment_terms: _Optional[str] = None
    delivery_timeline: _Optional[str] = None
    grand_total: _Optional[float] = None
    freight_amount_total: _Optional[float] = None
    loading_unloading_total: _Optional[float] = None
    validity_date: _Optional[str] = None
    date_received: _Optional[str] = None


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
    if payload.validity_date is not None:
        from datetime import date as _date
        try:
            quotation.validity_date = _date.fromisoformat(payload.validity_date) if payload.validity_date else None
        except Exception:
            pass
    if payload.date_received is not None:
        from datetime import date as _date
        try:
            quotation.date_received = _date.fromisoformat(payload.date_received) if payload.date_received else quotation.date_received
        except Exception:
            pass

    db.commit()
    db.refresh(quotation)
    return {"success": True, "quotation_id": quotation.id}


# ──────────────────────────────────────────────────
# Approve quotation for comparison (PM action)
# ──────────────────────────────────────────────────

@router.put("/{quotation_id}/approve-comparison")
def approve_for_comparison(
    quotation_id: int,
    db: Session = Depends(get_db)
):
    """Mark a quotation as approved for comparison by purchase manager.
    Only approved quotations appear in the comparison matrix.
    """
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if not quotation.is_latest:
        raise HTTPException(status_code=400, detail="Only the latest revision can be approved for comparison")
    quotation.approved_for_comparison = True
    db.commit()
    return {"success": True, "quotation_id": quotation.id, "approved_for_comparison": True}


@router.put("/{quotation_id}/unapprove-comparison")
def unapprove_from_comparison(
    quotation_id: int,
    db: Session = Depends(get_db)
):
    """Remove a quotation from comparison (PM can pull it back for editing)."""
    quotation = db.query(Quotation).filter(Quotation.id == quotation_id).first()
    if not quotation:
        raise HTTPException(status_code=404, detail="Quotation not found")
    quotation.approved_for_comparison = False
    db.commit()
    return {"success": True, "quotation_id": quotation.id, "approved_for_comparison": False}


# ──────────────────────────────────────────────────
# Edit individual quotation line items
# ──────────────────────────────────────────────────

class QuotationItemEditPayload(_BaseModel):
    brand_offered: _Optional[str] = None
    total_item_amount: _Optional[float] = None
    final_landed_rate: _Optional[float] = None
    remarks: _Optional[str] = None
    delivery_timeline: _Optional[str] = None
    payment_terms: _Optional[str] = None


@router.put("/{quotation_id}/items/{item_id}")
def edit_quotation_item(
    quotation_id: int,
    item_id: int,
    payload: QuotationItemEditPayload,
    db: Session = Depends(get_db)
):
    """Edit a specific quotation line item (per-material details)."""
    from app.models.quotation_item import QuotationItem
    qi = db.query(QuotationItem).filter(
        QuotationItem.id == item_id,
        QuotationItem.quotation_id == quotation_id
    ).first()
    if not qi:
        raise HTTPException(status_code=404, detail="Quotation item not found")

    if payload.brand_offered is not None:
        qi.brand_offered = payload.brand_offered
    if payload.total_item_amount is not None:
        qi.total_item_amount = payload.total_item_amount
    if payload.final_landed_rate is not None:
        qi.final_landed_rate = payload.final_landed_rate
    if payload.remarks is not None:
        qi.remarks = payload.remarks

    # If total_item_amount updated but not final_landed_rate, recalculate per-unit rate
    if payload.total_item_amount is not None and payload.final_landed_rate is None:
        rfq_item = db.query(RFQItem).filter(RFQItem.id == qi.rfq_item_id).first()
        if rfq_item and rfq_item.quantity and float(rfq_item.quantity) > 0:
            qi.final_landed_rate = float(payload.total_item_amount) / float(rfq_item.quantity)

    db.commit()
    db.refresh(qi)
    return {
        "success": True,
        "item_id": qi.id,
        "brand_offered": qi.brand_offered,
        "total_item_amount": float(qi.total_item_amount or 0),
        "final_landed_rate": float(qi.final_landed_rate or 0),
        "remarks": qi.remarks
    }

