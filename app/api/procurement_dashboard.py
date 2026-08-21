from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.rfq import RFQ
from app.models.rfq_vendor import RFQVendor
from app.models.quotation import Quotation
from app.services.requirement_service import RequirementService

router = APIRouter(
    prefix="/dashboard/procurement",
    tags=["Procurement Dashboard"]
)

templates = Jinja2Templates(directory="app/templates")


def _compute_stage(req=None, rfq=None, quote_count=0, approved_count=0, has_award=False, has_po=False):
    if has_po:
        return ("po_created", "PO Created", "indigo")
    if has_award:
        return ("awarded", "Awarded", "success")
    if rfq:
        s = rfq.status
        if s == "Closed":
            return ("closed", "Closed", "dark")
        if s == "Cancelled":
            return ("cancelled", "Cancelled", "danger")
        if s == "Negotiation":
            return ("negotiation", "Negotiation", "warning")
        if approved_count > 0:
            return ("in_comparison", f"In Comparison ({approved_count})", "purple")
        if quote_count > 0:
            return ("quotes_received", f"Quotes ({quote_count})", "info")
        if s in ("Sent", "Quotation Received"):
            return ("rfq_sent", "RFQ Sent", "primary")
        if s in ("Draft", "Pending Approval", "Approved"):
            return ("ready_to_send", "Ready to Send", "warning")
    if req:
        if req.status == "CANCELLED":
            return ("cancelled", "Cancelled", "danger")
        if req.status == "COMPLETED":
            return ("closed", "Completed", "dark")
    return ("draft", "Draft", "secondary")


@router.get("/", response_class=HTMLResponse)
def procurement_tracker(
    request: Request,
    db: Session = Depends(get_db),
    search: str = "",
    stage: str = "",
):
    from app.models.rfq_award import RFQAward
    from app.models.purchase_order import PurchaseOrder

    all_reqs = RequirementService.get_all_requirements(db, search=search, status="")
    enriched = []
    processed_rfq_ids = set()

    for req in all_reqs:
        rfq = db.query(RFQ).filter(RFQ.requirement_id == req.id).first()
        vendor_count = 0
        quote_count = 0
        approved_count = 0
        has_award = False
        has_po = False

        if rfq:
            processed_rfq_ids.add(rfq.id)
            vendor_count = db.query(RFQVendor).filter(RFQVendor.rfq_id == rfq.id).count()
            quote_count = db.query(Quotation).filter(
                Quotation.rfq_id == rfq.id, Quotation.is_latest == True
            ).count()
            approved_count = db.query(Quotation).filter(
                Quotation.rfq_id == rfq.id,
                Quotation.is_latest == True,
                Quotation.approved_for_comparison == True
            ).count()
            has_award = db.query(RFQAward).filter(RFQAward.rfq_id == rfq.id).count() > 0
            if has_award:
                has_po = db.query(PurchaseOrder).filter(PurchaseOrder.rfq_id == rfq.id).count() > 0

        stage_key, stage_label, stage_color = _compute_stage(
            req=req, rfq=rfq, quote_count=quote_count,
            approved_count=approved_count, has_award=has_award, has_po=has_po
        )

        if stage and stage_key != stage:
            continue

        search_lower = search.lower()
        if search_lower:
            fields = [req.requirement_number or "", req.project_name or "",
                      req.site_name or "", req.requested_by or "",
                      rfq.rfq_number if rfq else ""]
            if not any(search_lower in f.lower() for f in fields):
                continue

        enriched.append({
            "type": "requirement",
            "req": req,
            "rfq": rfq,
            "vendor_count": vendor_count,
            "quote_count": quote_count,
            "approved_count": approved_count,
            "has_award": has_award,
            "has_po": has_po,
            "can_compare": approved_count >= 2,
            "can_create_rfq": len(req.materials or []) > 0 and rfq is None,
            "stage_key": stage_key,
            "stage_label": stage_label,
            "stage_color": stage_color,
        })

    all_rfqs = db.query(RFQ).filter(RFQ.requirement_id == None).all()
    standalone = []
    for rfq in all_rfqs:
        if rfq.id in processed_rfq_ids:
            continue
        vendor_count = db.query(RFQVendor).filter(RFQVendor.rfq_id == rfq.id).count()
        quote_count = db.query(Quotation).filter(
            Quotation.rfq_id == rfq.id, Quotation.is_latest == True
        ).count()
        approved_count = db.query(Quotation).filter(
            Quotation.rfq_id == rfq.id,
            Quotation.is_latest == True,
            Quotation.approved_for_comparison == True
        ).count()
        has_award = db.query(RFQAward).filter(RFQAward.rfq_id == rfq.id).count() > 0
        has_po = False
        if has_award:
            has_po = db.query(PurchaseOrder).filter(PurchaseOrder.rfq_id == rfq.id).count() > 0

        stage_key, stage_label, stage_color = _compute_stage(
            rfq=rfq, quote_count=quote_count, approved_count=approved_count,
            has_award=has_award, has_po=has_po
        )
        search_lower = search.lower()
        if search_lower:
            fields = [rfq.rfq_number or "", rfq.project_name or "", rfq.site_name or ""]
            if not any(search_lower in f.lower() for f in fields):
                continue

        standalone.append({
            "type": "standalone_rfq",
            "rfq": rfq,
            "vendor_count": vendor_count,
            "quote_count": quote_count,
            "approved_count": approved_count,
            "has_award": has_award,
            "has_po": has_po,
            "can_compare": approved_count >= 2,
            "stage_key": stage_key,
            "stage_label": stage_label,
            "stage_color": stage_color,
        })

    archived_stages = {"closed", "cancelled"}
    active_items = [e for e in enriched if e["stage_key"] not in archived_stages]
    archived_req = [e for e in enriched if e["stage_key"] in archived_stages]
    active_standalone = [e for e in standalone if e["stage_key"] not in archived_stages]
    archived_standalone = [e for e in standalone if e["stage_key"] in archived_stages]

    return templates.TemplateResponse(
        request=request,
        name="procurement_tracker.html",
        context={
            "request": request,
            "active_items": active_items,
            "archived_items": archived_req + archived_standalone,
            "standalone_items": active_standalone,
            "search": search,
            "stage": stage,
            "total_active": len(active_items) + len(active_standalone),
        }
    )
