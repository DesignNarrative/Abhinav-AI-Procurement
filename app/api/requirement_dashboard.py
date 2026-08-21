from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db

from app.services.requirement_service import RequirementService

router = APIRouter(
    prefix="/dashboard/requirements",
    tags=["Requirement Dashboard"]
)

templates = Jinja2Templates(
    directory="app/templates"
)


# =====================================================
# Requirement List
# =====================================================

@router.get(
    "/",
    response_class=HTMLResponse
)
def requirement_management(
    request: Request,
    db: Session = Depends(get_db),
    search: str = "",
    status: str = ""
):
    """Requirements list is now the unified Procurement Tracker page."""
    return RedirectResponse(url="/dashboard/procurement/", status_code=302)



# =====================================================
# Create Requirement Page (merged into unified RFQ page)
# =====================================================

@router.get(
    "/create"
)
def create_requirement_page():
    """Requirements creation is merged into the unified RFQ page.

    Kept as a permanent redirect so old links/bookmarks keep working.
    """
    return RedirectResponse(
        url="/dashboard/rfq/create",
        status_code=307
    )


# =====================================================
# Requirement Details
# =====================================================

@router.get(
    "/{requirement_id}",
    response_class=HTMLResponse
)
def requirement_details(
    requirement_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    from app.models.rfq import RFQ
    from app.models.rfq_vendor import RFQVendor
    from app.models.quotation import Quotation
    from app.models.supplier import Supplier

    requirement = RequirementService.get_requirement_by_id(
        db=db,
        requirement_id=requirement_id
    )

    if not requirement:
        raise HTTPException(
            status_code=404,
            detail="Requirement not found"
        )

    materials = requirement.materials or []

    # ── Linked RFQ ──────────────────────────────────────────────
    rfq = db.query(RFQ).filter(RFQ.requirement_id == requirement_id).first()

    enriched_vendors = []
    quote_count = 0

    if rfq:
        rfq_vendors = db.query(RFQVendor).filter(RFQVendor.rfq_id == rfq.id).all()
        for rv in rfq_vendors:
            vendor = db.query(Supplier).filter(Supplier.id == rv.vendor_id).first()
            quotation = db.query(Quotation).filter(
                Quotation.rfq_id == rfq.id,
                Quotation.vendor_id == rv.vendor_id,
                Quotation.is_latest == True
            ).first()
            enriched_vendors.append({
                "rv": rv,
                "vendor": vendor,
                "quotation": quotation
            })
        quote_count = sum(1 for ev in enriched_vendors if ev["quotation"] is not None)

    return templates.TemplateResponse(
        request=request,
        name="requirement_details.html",
        context={
            "request": request,
            "requirement": requirement,
            "materials": materials,
            "material_count": len(materials),
            "can_generate_rfq": len(materials) > 0,
            "rfq": rfq,
            "enriched_vendors": enriched_vendors,
            "quote_count": quote_count,
            "can_compare": quote_count >= 2
        }
    )