"""
Document Intelligence API Router — Phase 1

Routes:
    POST   /document-intelligence/ingest    Ingest a new document
    GET    /document-intelligence/          List all ingested documents
    GET    /document-intelligence/{uuid}    Fetch a single document by UUID
"""

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    HTTPException,
    Query
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.services.document_intelligence_service import (
    ingest_document,
    list_ingested_documents,
    get_ingested_document,
    extract_text_from_pdf,
    classify_document,
    parse_with_llm
)
from app.services.entity_resolution_service import resolve_entities
from app.services.business_validation_service import validate_document_business
from app.services.quotation_draft_service import create_draft_quotation

router = APIRouter(
    prefix="/document-intelligence",
    tags=["Document Intelligence"]
)


# ──────────────────────────────────────────────────────────────
# POST /document-intelligence/ingest
# ──────────────────────────────────────────────────────────────

@router.post("/ingest")
def ingest(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Ingest a procurement document uploaded manually from the dashboard.

    - Validates file type (PDF, JPG, JPEG, PNG).
    - Validates file size (max 10 MB).
    - Detects and rejects duplicate files (by SHA-256 hash).
    - Saves file to uploads/quotation_documents/.
    - Creates a DocumentIngestionLog database record.
    - Returns the document UUID, file path, and processing status.
    """
    log = ingest_document(
        db=db,
        file=file,
        source="MANUAL_UPLOAD",
        sender_phone=None,
        supplier_id=None
    )

    return {
        "document_uuid": log.document_uuid,
        "original_filename": log.original_filename,
        "file_path": log.file_path,
        "file_size_bytes": log.file_size_bytes,
        "file_extension": log.file_extension,
        "source": log.source,
        "processing_status": log.processing_status,
        "created_at": str(log.created_at)
    }


# ──────────────────────────────────────────────────────────────
# GET /document-intelligence/
# ──────────────────────────────────────────────────────────────

@router.get("/")
def list_documents(
    status: str = Query(default=None, description="Filter by processing_status: PENDING, PROCESSING, DONE, FAILED"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """
    List all ingested procurement documents.

    Optional filter by processing_status.
    Supports pagination via limit and offset.
    """
    documents = list_ingested_documents(
        db=db,
        status=status,
        limit=limit,
        offset=offset
    )

    return [
        {
            "document_uuid": doc.document_uuid,
            "original_filename": doc.original_filename,
            "file_extension": doc.file_extension,
            "source": doc.source,
            "sender_phone": doc.sender_phone,
            "document_type": doc.document_type,
            "processing_status": doc.processing_status,
            "processing_error": doc.processing_error,
            "file_size_bytes": doc.file_size_bytes,
            "created_at": str(doc.created_at)
        }
        for doc in documents
    ]


# ──────────────────────────────────────────────────────────────
# GET /document-intelligence/{document_uuid}
# ──────────────────────────────────────────────────────────────

@router.get("/{document_uuid}")
def get_document(
    document_uuid: str,
    db: Session = Depends(get_db)
):
    """
    Fetch a single ingested document by its UUID.
    Returns full details including file path and processing status.
    """
    doc = get_ingested_document(db=db, document_uuid=document_uuid)

    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document with UUID '{document_uuid}' not found."
        )

    return {
        "id": doc.id,
        "document_uuid": doc.document_uuid,
        "original_filename": doc.original_filename,
        "stored_filename": doc.stored_filename,
        "file_path": doc.file_path,
        "file_hash": doc.file_hash,
        "file_size_bytes": doc.file_size_bytes,
        "mime_type": doc.mime_type,
        "file_extension": doc.file_extension,
        "source": doc.source,
        "sender_phone": doc.sender_phone,
        "supplier_id": doc.supplier_id,
        "document_type": doc.document_type,
        "processing_status": doc.processing_status,
        "processing_error": doc.processing_error,
        "created_at": str(doc.created_at),
        "updated_at": str(doc.updated_at)
    }


# ──────────────────────────────────────────────────────────────
# POST /document-intelligence/{document_uuid}/extract-text
# ──────────────────────────────────────────────────────────────

@router.post("/{document_uuid}/extract-text")
def extract_text(
    document_uuid: str,
    db: Session = Depends(get_db)
):
    """
    Trigger digital text extraction for a specific PDF document.

    - Validates that the document is a PDF.
    - Extracts text from all pages using PyMuPDF.
    - Saves the extracted text as a parallel .txt file on disk.
    - Flags images or scanned PDFs as requiring OCR.
    - Updates log status to 'PROCESSING'.
    """
    result = extract_text_from_pdf(db=db, document_uuid=document_uuid)
    return result


# ──────────────────────────────────────────────────────────────
# POST /document-intelligence/{document_uuid}/classify
# ──────────────────────────────────────────────────────────────

@router.post("/{document_uuid}/classify")
def classify(
    document_uuid: str,
    db: Session = Depends(get_db)
):
    """
    Trigger rules-based keyword classification for a specific document.

    - Scans the extracted text file.
    - Resolves document type (QUOTATION, PURCHASE_ORDER, INVOICE, etc.).
    - Updates log 'document_type' column.
    """
    doc_type = classify_document(db=db, document_uuid=document_uuid)
    return {
        "document_uuid": document_uuid,
        "document_type": doc_type
    }


# ──────────────────────────────────────────────────────────────
# POST /document-intelligence/{document_uuid}/parse
# ──────────────────────────────────────────────────────────────

@router.post("/{document_uuid}/parse")
def parse(
    document_uuid: str,
    db: Session = Depends(get_db)
):
    """
    Trigger structured AI extraction (LLM) for a specific document.

    - Resolves raw text extraction.
    - Routes to the configured AI extraction provider (Gemini, Groq, Ollama).
    - Serializes output to JSON schema and saves to disk.
    - Transitions DB status to 'DONE'.
    """
    result = parse_with_llm(db=db, document_uuid=document_uuid)
    return result


# ──────────────────────────────────────────────────────────────
# POST /document-intelligence/{document_uuid}/resolve-entities
# ──────────────────────────────────────────────────────────────

@router.post("/{document_uuid}/resolve-entities")
def resolve_document_entities(
    document_uuid: str,
    threshold: float = Query(80.0, ge=0.0, le=100.0, description="Similarity matching threshold percent"),
    db: Session = Depends(get_db)
):
    """
    Trigger entity resolution for a specific document.

    - Resolves vendor matching using exact GST match or fuzzy name matching.
    - Resolves line item material matching using fuzzy name matching.
    - Overwrites the extraction JSON output on disk with resolved codes.
    """
    result = resolve_entities(db=db, document_uuid=document_uuid, threshold=threshold)
    return result


# ──────────────────────────────────────────────────────────────
# POST /document-intelligence/{document_uuid}/validate
# ──────────────────────────────────────────────────────────────

@router.post("/{document_uuid}/validate")
def validate_document(
    document_uuid: str,
    db: Session = Depends(get_db)
):
    """
    Trigger mathematical and business rules validation for a specific document.

    - Verifies line item amounts (quantity * rate = total).
    - Verifies grand total sum matching.
    - Flags validity date age/expiry warnings.
    - Flags missing payment or delivery terms.
    - Overwrites the extraction JSON output on disk with validation results.
    """
    result = validate_document_business(db=db, document_uuid=document_uuid)
    return result


# ──────────────────────────────────────────────────────────────
# POST /document-intelligence/{document_uuid}/create-draft-quotation
# ──────────────────────────────────────────────────────────────

@router.post("/{document_uuid}/create-draft-quotation")
def create_quotation_draft(
    document_uuid: str,
    rfq_id: int = Query(..., description="The RFQ ID to associate this quotation with"),
    created_by: str = Query("AI_SYSTEM", description="Username stamped on the quotation record"),
    fuzzy_threshold: float = Query(80.0, ge=0.0, le=100.0, description="Similarity threshold for matching line items to RFQ items"),
    db: Session = Depends(get_db)
):
    """
    Auto-draft a Quotation and QuotationItems from a validated AI extraction.

    - Resolves the vendor against the suppliers database table.
    - Fuzzy-matches extracted line items to RFQ items.
    - Creates Quotation and QuotationItem records in the database.
    - Returns the created quotation ID and line item count.
    """
    result = create_draft_quotation(
        db=db,
        document_uuid=document_uuid,
        rfq_id=rfq_id,
        created_by=created_by,
        fuzzy_threshold=fuzzy_threshold,
    )
    return result


# ──────────────────────────────────────────────────────────────
# PATCH /document-intelligence/{document_uuid}/approve
# ──────────────────────────────────────────────────────────────
from pydantic import BaseModel
from typing import List, Optional

class ApproveItem(BaseModel):
    id: int
    brand_offered: Optional[str] = None
    quoted_quantity: Optional[float] = None
    basic_rate: Optional[float] = None
    tax_percent: Optional[float] = None

class ApproveDocumentRequest(BaseModel):
    payment_terms: Optional[str] = None
    delivery_timeline: Optional[str] = None
    grand_total: Optional[float] = None
    items: Optional[List[ApproveItem]] = None


@router.patch("/{document_uuid}/approve")
def approve_document(
    document_uuid: str,
    payload: Optional[ApproveDocumentRequest] = None,
    approved_by: str = Query("HUMAN_REVIEWER", description="Name/ID of reviewer approving"),
    db: Session = Depends(get_db)
):
    """
    Approve the AI-drafted quotation for a specific document.

    - Finds the Draft quotation linked to this document UUID.
    - Updates Quotation status from 'Draft' to 'Approved'.
    - Returns updated quotation details.
    """
    from app.models.document_ingestion_log import DocumentIngestionLog
    from app.models.quotation import Quotation
    from app.models.quotation_item import QuotationItem
    import os, json
    from app.services.document_intelligence_service import INGEST_FOLDER

    log = db.query(DocumentIngestionLog).filter(
        DocumentIngestionLog.document_uuid == document_uuid
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Find the draft quotation by looking up the extraction JSON for the quotation number
    json_path = os.path.join(INGEST_FOLDER, f"{document_uuid}_extracted.json").replace("\\", "/")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=400, detail="No extraction JSON found. Run /parse first.")

    with open(json_path, "r", encoding="utf-8") as f:
        extraction_data = json.load(f)

    doc_number = extraction_data.get("document_metadata", {}).get("document_number", {}).get("value")
    quotation_number = doc_number if doc_number else f"AI-DRAFT-{document_uuid[:8].upper()}"

    quotation = db.query(Quotation).filter(Quotation.quotation_number == quotation_number).first()
    if not quotation:
        raise HTTPException(
            status_code=404,
            detail=f"No draft quotation found with number '{quotation_number}'. Run /create-draft-quotation first."
        )

    if quotation.status == "Approved":
        return {"message": "Quotation is already approved.", "quotation_id": quotation.id, "status": quotation.status}

    # Save any edits from the reviewer
    if payload:
        if payload.payment_terms is not None:
            quotation.payment_terms = payload.payment_terms
        if payload.delivery_timeline is not None:
            quotation.delivery_timeline = payload.delivery_timeline
        if payload.grand_total is not None:
            quotation.grand_total = payload.grand_total

        if payload.items:
            for it in payload.items:
                q_item = db.query(QuotationItem).filter(QuotationItem.id == it.id).first()
                if q_item:
                    if it.brand_offered is not None:
                        q_item.brand_offered = it.brand_offered
                    if it.quoted_quantity is not None:
                        q_item.quoted_quantity = it.quoted_quantity
                    if it.basic_rate is not None:
                        q_item.basic_rate = it.basic_rate
                    if it.tax_percent is not None:
                        q_item.tax_percent = it.tax_percent

                    # Recompute item total & landed rate
                    qty = q_item.quoted_quantity or 0.0
                    rate = q_item.basic_rate or 0.0
                    tax = q_item.tax_percent or 0.0
                    discount = q_item.discount_percent or 0.0

                    taxable = float(rate) * (1 - float(discount) / 100.0)
                    landed = taxable * (1 + float(tax) / 100.0)
                    calculated_total = float(qty) * landed

                    q_item.final_landed_rate = round(landed, 3)
                    q_item.total_item_amount = calculated_total

    quotation.status = "Approved"
    db.commit()
    db.refresh(quotation)

    return {
        "message": f"Quotation '{quotation_number}' approved by '{approved_by}'.",
        "quotation_id": quotation.id,
        "quotation_number": quotation.quotation_number,
        "status": quotation.status,
    }


# ──────────────────────────────────────────────────────────────
# PATCH /document-intelligence/{document_uuid}/reject
# ──────────────────────────────────────────────────────────────

@router.patch("/{document_uuid}/reject")
def reject_document(
    document_uuid: str,
    rejected_by: str = Query("HUMAN_REVIEWER", description="Name/ID of reviewer rejecting"),
    reason: str = Query("", description="Reason for rejection"),
    db: Session = Depends(get_db)
):
    """
    Reject the AI-drafted quotation for a specific document.

    - Finds the Draft quotation linked to this document UUID.
    - Updates Quotation status from 'Draft' to 'Rejected'.
    - Updates the ingestion log processing_error with the rejection reason.
    """
    from app.models.document_ingestion_log import DocumentIngestionLog
    from app.models.quotation import Quotation
    import os, json
    from app.services.document_intelligence_service import INGEST_FOLDER

    log = db.query(DocumentIngestionLog).filter(
        DocumentIngestionLog.document_uuid == document_uuid
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="Document not found.")

    json_path = os.path.join(INGEST_FOLDER, f"{document_uuid}_extracted.json").replace("\\", "/")
    if not os.path.exists(json_path):
        raise HTTPException(status_code=400, detail="No extraction JSON found. Run /parse first.")

    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    doc_number = payload.get("document_metadata", {}).get("document_number", {}).get("value")
    quotation_number = doc_number if doc_number else f"AI-DRAFT-{document_uuid[:8].upper()}"

    quotation = db.query(Quotation).filter(Quotation.quotation_number == quotation_number).first()
    if not quotation:
        raise HTTPException(
            status_code=404,
            detail=f"No draft quotation found with number '{quotation_number}'. Run /create-draft-quotation first."
        )

    quotation.status = "Rejected"
    log.processing_error = f"Rejected by '{rejected_by}': {reason}" if reason else f"Rejected by '{rejected_by}'"
    db.commit()
    db.refresh(quotation)

    return {
        "message": f"Quotation '{quotation_number}' rejected by '{rejected_by}'.",
        "quotation_id": quotation.id,
        "quotation_number": quotation.quotation_number,
        "status": quotation.status,
        "reason": reason,
    }

