"""
Document Intelligence Dashboard — Phase 10
Human-in-the-Loop Verification UI

Routes:
    GET  /dashboard/document-intelligence/         List all ingested documents
    GET  /dashboard/document-intelligence/{uuid}   Review a single document
"""

import os
import json

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.document_ingestion_log import DocumentIngestionLog
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.supplier import Supplier
from app.services.document_intelligence_service import INGEST_FOLDER

router = APIRouter(
    prefix="/dashboard/document-intelligence",
    tags=["Document Intelligence Dashboard"]
)

templates = Jinja2Templates(directory="app/templates")


# ──────────────────────────────────────────────────────────────
# GET /dashboard/document-intelligence/
# ──────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def document_intelligence_list(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    List all ingested procurement documents with their processing status.
    """
    logs = (
        db.query(DocumentIngestionLog)
        .order_by(DocumentIngestionLog.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="document_intelligence_list.html",
        context={"request": request, "logs": logs}
    )


# ──────────────────────────────────────────────────────────────
# GET /dashboard/document-intelligence/{document_uuid}
# ──────────────────────────────────────────────────────────────

@router.get("/{document_uuid}", response_class=HTMLResponse)
def document_intelligence_review(
    document_uuid: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Human-in-the-Loop review page for a single ingested document.
    Shows the AI-extracted payload alongside validation statuses.
    Provides Approve / Reject controls.
    """
    log = db.query(DocumentIngestionLog).filter(
        DocumentIngestionLog.document_uuid == document_uuid
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Load extraction JSON if it exists
    extraction_payload = None
    json_path = os.path.join(INGEST_FOLDER, f"{document_uuid}_extracted.json").replace("\\", "/")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            extraction_payload = json.load(f)

    # Load the draft quotation if one has been created
    draft_quotation = None
    draft_items = []
    rfq = None
    if extraction_payload:
        doc_number = None
        if extraction_payload.get("document_metadata", {}).get("document_number", {}).get("value"):
            doc_number = extraction_payload["document_metadata"]["document_number"]["value"]

        if doc_number:
            draft_quotation = db.query(Quotation).filter(
                Quotation.quotation_number == doc_number
            ).first()
        else:
            # Fallback: look for AI-DRAFT prefixed quotations
            fallback_number = f"AI-DRAFT-{document_uuid[:8].upper()}"
            draft_quotation = db.query(Quotation).filter(
                Quotation.quotation_number == fallback_number
            ).first()

        if draft_quotation:
            q_items = db.query(QuotationItem).filter(
                QuotationItem.quotation_id == draft_quotation.id
            ).all()
            rfq = db.query(RFQ).filter(RFQ.id == draft_quotation.rfq_id).first()

            for q_item in q_items:
                rfq_item = db.query(RFQItem).filter(RFQItem.id == q_item.rfq_item_id).first()
                draft_items.append({
                    "q_item": q_item,
                    "rfq_item": rfq_item,
                })

    # For quotations without a draft yet (e.g. ambiguous RFQ resolution),
    # offer the supplier's candidate RFQs so the reviewer can pick one manually.
    candidate_rfqs = []
    if (
        not draft_quotation
        and log.supplier_id
        and (log.document_type or "").upper() == "QUOTATION"
    ):
        candidate_rfqs = (
            db.query(RFQ)
            .join(RFQVendor, RFQVendor.rfq_id == RFQ.id)
            .filter(
                RFQVendor.vendor_id == log.supplier_id,
                RFQ.status.notin_(["Closed", "Cancelled"])
            )
            .order_by(RFQ.created_at.desc())
            .all()
        )

    return templates.TemplateResponse(
        request=request,
        name="document_intelligence_review.html",
        context={
            "request": request,
            "log": log,
            "extraction_payload": extraction_payload,
            "draft_quotation": draft_quotation,
            "draft_items": draft_items,
            "rfq": rfq,
            "candidate_rfqs": candidate_rfqs,
            "document_uuid": document_uuid,
        }
    )
