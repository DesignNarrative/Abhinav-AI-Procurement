from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.supplier import Supplier
from app.models.quotation import Quotation
from app.services.rfq_service import RFQService

router = APIRouter(
    prefix="/dashboard/rfq",
    tags=["RFQ Dashboard"]
)

templates = Jinja2Templates(
    directory="app/templates"
)


@router.get("/", response_class=HTMLResponse)
def rfq_management(
    request: Request,
    status: str = "",
    db: Session = Depends(get_db)
):
    rfqs = RFQService.list_rfqs(db, status=status if status else None)
    return templates.TemplateResponse(
        request=request,
        name="rfq_management.html",
        context={
            "request": request,
            "rfqs": rfqs,
            "status_filter": status
        }
    )


@router.get("/create", response_class=HTMLResponse)
def rfq_create_form(
    request: Request,
    db: Session = Depends(get_db)
):
    vendors = db.query(Supplier).filter(
        Supplier.registration_status == "APPROVED"
    ).order_by(Supplier.company_name).all()

    return templates.TemplateResponse(
        request=request,
        name="rfq_create.html",
        context={
            "request": request,
            "vendors": vendors
        }
    )


@router.get("/{rfq_id}", response_class=HTMLResponse)
def rfq_details(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    items = db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()
    rfq_vendors = db.query(RFQVendor).filter(RFQVendor.rfq_id == rfq_id).all()

    # Enrich vendors
    enriched_vendors = []
    for rv in rfq_vendors:
        vendor = db.query(Supplier).filter(Supplier.id == rv.vendor_id).first()
        quotation = db.query(Quotation).filter(
            Quotation.rfq_id == rfq_id,
            Quotation.vendor_id == rv.vendor_id,
            Quotation.is_latest == True
        ).first()
        
        enriched_vendors.append({
            "rv": rv,
            "vendor": vendor,
            "quotation": quotation
        })

    return templates.TemplateResponse(
        request=request,
        name="rfq_details.html",
        context={
            "request": request,
            "rfq": rfq,
            "items": items,
            "enriched_vendors": enriched_vendors
        }
    )


@router.get("/{rfq_id}/comparison", response_class=HTMLResponse)
def rfq_comparison(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Side-by-side quotation comparison + award page for an RFQ."""
    from app.services.comparison_service import ComparisonService

    comparison = ComparisonService.build_comparison(db, rfq_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="RFQ not found")

    return templates.TemplateResponse(
        request=request,
        name="rfq_comparison.html",
        context={
            "request": request,
            "comparison": comparison
        }
    )
