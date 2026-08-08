"""
Document Intelligence Service — Phase 1: Ingestion & Storage

This is the master service for the Document Intelligence Engine.
Each future phase will ADD new functions to this service.
This service must NEVER be broken by future additions.

Phase 1  : ingest_document()          — File save + hash + DB log
Phase 2  : extract_text_from_pdf()    — PyMuPDF parser
Phase 3  : extract_text_via_ocr()     — PaddleOCR engine
Phase 4  : classify_document()        — Document type classifier
Phase 6  : parse_with_llm()           — LLM provider abstraction
Phase 7  : resolve_entities()         — Semantic KB matching
Phase 8  : validate_document()        — Business validation engine
Phase 9  : create_draft_quotation()   — Auto-create quotation from extraction
"""

import os
import uuid
import hashlib
import shutil
import fitz

from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException

from app.models.document_ingestion_log import DocumentIngestionLog
from app.services.extraction import get_extraction_provider


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

INGEST_FOLDER = "uploads/quotation_documents"

# Maximum file size: 10 MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# Allowed file types for procurement document ingestion
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png"
}

# Maps MIME type to file extension when filename is not available
# (used for WhatsApp media downloads where original filename is unknown)
MIME_TO_EXTENSION = {
    "application/pdf": ".pdf",
    "image/jpeg":      ".jpg",
    "image/jpg":       ".jpg",
    "image/png":       ".png"
}


# ──────────────────────────────────────────────────────────────
# Utility Functions
# ──────────────────────────────────────────────────────────────

def _compute_sha256(file_bytes: bytes) -> str:
    """Compute SHA-256 hex digest of a file's binary content."""
    return hashlib.sha256(file_bytes).hexdigest()


def _ensure_ingest_folder() -> None:
    """Create the ingest folder if it does not exist."""
    os.makedirs(INGEST_FOLDER, exist_ok=True)


# ──────────────────────────────────────────────────────────────
# Phase 1: Ingest Document
# ──────────────────────────────────────────────────────────────

def ingest_document(
    db: Session,
    file: UploadFile,
    source: str = "MANUAL_UPLOAD",
    sender_phone: str = None,
    supplier_id: int = None
) -> DocumentIngestionLog:
    """
    Accept an uploaded file, validate it, deduplicate by SHA-256 hash,
    save it to disk, and create a DocumentIngestionLog database record.

    Args:
        db            : SQLAlchemy session.
        file          : Uploaded file from FastAPI.
        source        : 'MANUAL_UPLOAD' or 'WHATSAPP'.
        sender_phone  : WhatsApp number (nullable for manual uploads).
        supplier_id   : Resolved supplier FK (nullable, filled in Phase 7).

    Returns:
        DocumentIngestionLog instance (either new or existing duplicate).

    Raises:
        HTTPException 400: Invalid file type or file too large.
        HTTPException 500: Unexpected storage or database error.
    """
    _ensure_ingest_folder()

    # ── Step 1: Validate file extension ──────────────────────
    original_filename = file.filename or "unknown"
    file_extension = os.path.splitext(original_filename)[1].lower()

    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{file_extension}' is not allowed. "
                f"Accepted types: PDF, JPG, JPEG, PNG."
            )
        )

    # ── Step 2: Read file bytes once ─────────────────────────
    file_bytes = file.file.read()
    file_size = len(file_bytes)

    if file_size == 0:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if file_size > MAX_FILE_SIZE_BYTES:
        size_mb = round(file_size / (1024 * 1024), 2)
        raise HTTPException(
            status_code=400,
            detail=(
                f"File size {size_mb} MB exceeds maximum allowed size of "
                f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
            )
        )

    # ── Step 3: Compute SHA-256 hash ─────────────────────────
    file_hash = _compute_sha256(file_bytes)

    # ── Step 4: Duplicate detection ──────────────────────────
    existing = db.query(DocumentIngestionLog).filter(
        DocumentIngestionLog.file_hash == file_hash
    ).first()

    if existing:
        # Return the existing record — no duplicate storage
        return existing

    # ── Step 5: Determine MIME type ──────────────────────────
    content_type = file.content_type or ""
    mime_type = content_type.lower().split(";")[0].strip()

    # ── Step 6: Generate UUID filename and save to disk ──────
    doc_uuid = str(uuid.uuid4())
    stored_filename = doc_uuid + file_extension
    file_path = os.path.join(INGEST_FOLDER, stored_filename)

    try:
        with open(file_path, "wb") as f:
            f.write(file_bytes)
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save file to storage: {str(e)}"
        )

    # Normalize path separator for cross-platform compatibility
    file_path = file_path.replace("\\", "/")

    # ── Step 7: Create database record ───────────────────────
    log = DocumentIngestionLog(
        document_uuid=doc_uuid,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_hash=file_hash,
        file_size_bytes=file_size,
        mime_type=mime_type if mime_type else None,
        file_extension=file_extension,
        source=source,
        sender_phone=sender_phone,
        supplier_id=supplier_id,
        document_type=None,       # Filled by Phase 4 (Classifier)
        processing_status="PENDING",
        processing_error=None
    )

    try:
        db.add(log)
        db.commit()
        db.refresh(log)
    except Exception as e:
        db.rollback()
        # Clean up saved file to avoid orphaned files
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=500,
            detail=f"Database error while logging ingestion: {str(e)}"
        )

    return log


# ──────────────────────────────────────────────────────────────
# Phase 1: List Ingested Documents
# ──────────────────────────────────────────────────────────────

def list_ingested_documents(
    db: Session,
    status: str = None,
    limit: int = 50,
    offset: int = 0
) -> list:
    """
    Return a paginated list of all ingested documents.

    Args:
        db     : SQLAlchemy session.
        status : Optional filter by processing_status.
        limit  : Max rows to return (default 50).
        offset : Pagination offset (default 0).

    Returns:
        List of DocumentIngestionLog instances.
    """
    query = db.query(DocumentIngestionLog)

    if status:
        query = query.filter(
            DocumentIngestionLog.processing_status == status
        )

    return (
        query
        .order_by(DocumentIngestionLog.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_ingested_document(
    db: Session,
    document_uuid: str
) -> DocumentIngestionLog:
    """
    Fetch a single ingested document by its UUID.

    Args:
        db            : SQLAlchemy session.
        document_uuid : UUID string assigned at ingest time.

    Returns:
        DocumentIngestionLog or None.
    """
    return db.query(DocumentIngestionLog).filter(
        DocumentIngestionLog.document_uuid == document_uuid
    ).first()


# ──────────────────────────────────────────────────────────────
# Phase 2: PDF Digital Text Extraction
# ──────────────────────────────────────────────────────────────

def extract_text_from_pdf(
    db: Session,
    document_uuid: str
) -> dict:
    """
    Master text extraction orchestrator:
    1. If file is a digital PDF, attempts digital text extraction (fast, CPU-only).
    2. If digital text is missing/scanned or the file is an image, falls back
       automatically to local OCR extraction (PaddleOCR CPU-only).

    Args:
        db            : SQLAlchemy session.
        document_uuid : UUID string of the ingested document.

    Returns:
        dict containing extraction metrics and preview.
    """
    log = get_ingested_document(db, document_uuid)
    if not log:
        raise HTTPException(
            status_code=404,
            detail=f"Ingestion log for document UUID '{document_uuid}' not found."
        )

    # If it is an image, go directly to OCR
    if log.file_extension.lower() in [".jpg", ".jpeg", ".png"]:
        return extract_text_via_ocr(db, document_uuid)

    if log.file_extension.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{log.file_extension}'. Only PDF and image uploads are supported."
        )

    # First attempt digital text extraction (Phase 2)
    # Check if a digital text file already exists for this document
    text_filename = f"{document_uuid}_extracted.txt"
    text_path = os.path.join(INGEST_FOLDER, text_filename).replace("\\", "/")

    if os.path.exists(text_path):
        with open(text_path, "r", encoding="utf-8") as f:
            total_text = f.read()

        # If the existing file is too short, it's from a failed/incomplete run —
        # delete it and re-run extraction fresh below.
        if len(total_text.strip()) >= 50:
            doc_type = log.document_type
            if not doc_type:
                try:
                    doc_type = classify_document(db, document_uuid)
                except Exception:
                    doc_type = "UNKNOWN"

            return {
                "document_uuid": document_uuid,
                "requires_ocr": False,
                "page_count": 0,
                "character_count": len(total_text),
                "extracted_text_path": text_path,
                "document_type": doc_type,
                "preview": total_text[:250] + ("..." if len(total_text) > 250 else "")
            }
        else:
            print(f"[EXTRACTION] Existing text file for {document_uuid} is too short ({len(total_text.strip())} chars). Re-extracting...")
            os.remove(text_path)

    # Open PDF with PyMuPDF to test digital layer
    try:
        doc = fitz.open(log.file_path)
        page_count = len(doc)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to open PDF document: {str(e)}"
        )

    extracted_pages = []
    try:
        for page in doc:
            page_text = page.get_text() or ""
            extracted_pages.append(page_text)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error occurred during digital text read: {str(e)}"
        )
    finally:
        doc.close()

    total_text = "\n".join(extracted_pages).strip()

    # Fallback to OCR if digital text is empty or too short
    if len(total_text) < 50:
        return extract_text_via_ocr(db, document_uuid)

    # Save digital text
    try:
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(total_text)
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save extracted digital text: {str(e)}"
        )

    # Update database log status
    try:
        log.processing_status = "PROCESSING"
        db.commit()
        db.refresh(log)
    except Exception as e:
        db.rollback()
        if os.path.exists(text_path):
            os.remove(text_path)
        raise HTTPException(
            status_code=500,
            detail=f"Database error while updating processing status: {str(e)}"
        )

    # Classify document automatically
    try:
        doc_type = classify_document(db, document_uuid)
    except Exception:
        doc_type = "UNKNOWN"

    return {
        "document_uuid": document_uuid,
        "requires_ocr": False,
        "page_count": len(extracted_pages),
        "character_count": len(total_text),
        "extracted_text_path": text_path,
        "document_type": doc_type,
        "preview": total_text[:250] + ("..." if len(total_text) > 250 else "")
    }


# ──────────────────────────────────────────────────────────────
# Phase 3: Local OCR Extraction
# ──────────────────────────────────────────────────────────────

def extract_text_via_ocr(
    db: Session,
    document_uuid: str
) -> dict:
    """
    Open the ingested image or PDF, convert pages to PNG if PDF,
    and run local PaddleOCR to extract text blocks.
    Saves the extracted text to a parallel text file on disk.

    Args:
        db            : SQLAlchemy session.
        document_uuid : UUID string of the ingested document.

    Returns:
        dict containing extraction metrics and preview.
    """
    import tempfile

    log = get_ingested_document(db, document_uuid)
    if not log:
        raise HTTPException(
            status_code=404,
            detail=f"Ingestion log for document UUID '{document_uuid}' not found."
        )

    if not os.path.exists(log.file_path):
        raise HTTPException(
            status_code=500,
            detail=f"Source file not found at path '{log.file_path}'."
        )

    temp_dir = None
    images_paths = []

    try:
        # Step 1: Prepare pages as images
        if log.file_extension.lower() in [".jpg", ".jpeg", ".png"]:
            images_paths.append(log.file_path)
        elif log.file_extension.lower() == ".pdf":
            temp_dir = tempfile.mkdtemp()
            try:
                doc = fitz.open(log.file_path)
                for page_idx, page in enumerate(doc):
                    pix = page.get_pixmap(dpi=150)
                    img_path = os.path.join(temp_dir, f"page_{page_idx}.png")
                    pix.save(img_path)
                    images_paths.append(img_path)
                doc.close()
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to convert PDF pages to images for OCR: {str(e)}"
                )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"OCR extraction is not supported for extension '{log.file_extension}'."
            )

        # Step 2 & 3: Run vision OCR (Gemini) on the prepared page images.
        # Replaces the previous local PaddleOCR engine, which required the
        # heavy paddlepaddle dependency. Gemini vision reuses the same REST
        # infrastructure already configured for LLM extraction.
        from app.services.extraction.vision_ocr import ocr_images_to_text
        total_text = ocr_images_to_text(images_paths).strip()

    finally:
        # Cleanup temporary directory if generated
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Save extracted text to a parallel text file
    text_filename = f"{document_uuid}_extracted.txt"
    text_path = os.path.join(INGEST_FOLDER, text_filename).replace("\\", "/")

    try:
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(total_text)
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save extracted OCR text to disk: {str(e)}"
        )

    # Update database log status
    try:
        log.processing_status = "PROCESSING"
        db.commit()
        db.refresh(log)
    except Exception as e:
        db.rollback()
        if os.path.exists(text_path):
            os.remove(text_path)
        raise HTTPException(
            status_code=500,
            detail=f"Database error while updating processing status: {str(e)}"
        )

    # Classify document automatically
    try:
        doc_type = classify_document(db, document_uuid)
    except Exception:
        doc_type = "UNKNOWN"

    return {
        "document_uuid": document_uuid,
        "requires_ocr": True,
        "page_count": len(images_paths),
        "character_count": len(total_text),
        "extracted_text_path": text_path,
        "document_type": doc_type,
        "preview": total_text[:250] + ("..." if len(total_text) > 250 else "")
    }


# ──────────────────────────────────────────────────────────────
# Phase 4: Document Classification & Routing
# ──────────────────────────────────────────────────────────────

CLASSIFICATION_RULES = {
    "QUOTATION": ["quotation", "quote", "estimate", "proforma invoice", "est-", "qtn", "qt-", "sales order", "order confirmation", "order acknowledgment"],
    "PURCHASE_ORDER": ["purchase order", "po no", "po-", "po_no", "order placement"],
    "INVOICE": ["tax invoice", "invoice", "bill", "cash memo", "invoice no", "inv-"],
    "DELIVERY_CHALLAN": ["delivery challan", "delivery note", "challan no", "dispatch note", "gate pass"],
    "GRN": ["goods receipt note", "grn", "material receipt", "mrv", "receive note"],
    "TEST_CERTIFICATE": ["test certificate", "mill test", "tc", "chemical composition", "mechanical properties"]
}


def classify_document_with_llm(text: str) -> str:
    """
    LLM-based semantic document classifier using Gemini.
    Called as a fallback when keyword scoring is low or ambiguous.
    Returns 'QUOTATION', 'INVOICE', or 'UNKNOWN'.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "UNKNOWN"

    # Only send the first 4000 characters to keep the call fast and cheap
    truncated_text = text[:4000].strip()
    if not truncated_text:
        return "UNKNOWN"

    prompt = (
        "Analyze the following text extracted from a document sent by a supplier.\n"
        "Classify this document into exactly ONE of the following categories:\n"
        "- QUOTATION (price quote, estimate, proforma invoice, rates sheet, cost breakdown, offer letter with prices)\n"
        "- INVOICE (tax invoice, bill, payment request, cash memo)\n"
        "- OTHER (GST certificate, MSME certificate, product catalogue, test report, casual chat, photo, or anything else)\n\n"
        "Rules:\n"
        "1. If you see item names, quantities, unit prices, or totals — it is QUOTATION or INVOICE.\n"
        "2. If it contains 'tax invoice', 'invoice no', 'bill to' — it is INVOICE.\n"
        "3. If it mentions 'quotation', 'quote', 'estimate', 'proforma' — it is QUOTATION.\n"
        "4. If it is a certificate, catalogue, photo, or casual message — it is OTHER.\n\n"
        "Respond with EXACTLY ONE WORD from: QUOTATION, INVOICE, OTHER — and nothing else.\n\n"
        f"Document Text:\n\"\"\"\n{truncated_text}\n\"\"\""
    )

    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        import httpx
        r = httpx.post(url, json=payload, timeout=30.0)
        if r.status_code == 200:
            resp_json = r.json()
            result = resp_json["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
            # Extract only the classification word even if LLM adds extra text
            if "QUOTATION" in result:
                return "QUOTATION"
            elif "INVOICE" in result:
                return "INVOICE"
        else:
            print(f"[LLM CLASSIFIER] Gemini returned status {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[LLM CLASSIFIER] Gemini classification request failed: {e}")

    return "UNKNOWN"

def classify_document(
    db: Session,
    document_uuid: str
) -> str:
    """
    Classify the ingested document using rules-based keyword matching.
    Scans the extracted text file to determine the document type.
    Updates the 'document_type' column in the ingestion logs.

    Args:
        db            : SQLAlchemy session.
        document_uuid : UUID string of the ingested document.

    Returns:
        str: Classified document type (e.g. 'QUOTATION', 'PURCHASE_ORDER').
    """
    log = get_ingested_document(db, document_uuid)
    if not log:
        raise HTTPException(
            status_code=404,
            detail=f"Ingestion log for document UUID '{document_uuid}' not found."
        )

    # Resolve extracted text path
    text_filename = f"{document_uuid}_extracted.txt"
    text_path = os.path.join(INGEST_FOLDER, text_filename).replace("\\", "/")

    if not os.path.exists(text_path):
        raise HTTPException(
            status_code=400,
            detail=f"Extracted text file not found for document UUID '{document_uuid}'. Run text extraction first."
        )

    try:
        with open(text_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read extracted text file: {str(e)}"
        )

    text_lower = text.lower()
    scores = {k: 0 for k in CLASSIFICATION_RULES.keys()}

    # Priorities & special matches
    if "proforma invoice" in text_lower:
        scores["QUOTATION"] += 5
    if "tax invoice" in text_lower:
        scores["INVOICE"] += 5
    if "sales order" in text_lower:
        scores["INVOICE"] += 3

    for doc_type, keywords in CLASSIFICATION_RULES.items():
        for kw in keywords:
            count = text_lower.count(kw)
            scores[doc_type] += count

    best_type = max(scores, key=scores.get)
    classified_type = best_type if scores[best_type] > 0 else "UNKNOWN"

    # ── LLM Fallback: if keyword score is low or UNKNOWN, ask Gemini to read the text ──
    # This handles random filenames like IMG-8827.jpg or doc_new.pdf that suppliers send
    if classified_type == "UNKNOWN" or scores.get(best_type, 0) < 2:
        print(f"[CLASSIFIER] Keyword score low ({scores.get(best_type, 0)}), invoking Gemini LLM fallback...")
        llm_type = classify_document_with_llm(text)
        print(f"[CLASSIFIER] Gemini LLM classified document as: {llm_type}")
        if llm_type in ["QUOTATION", "INVOICE"]:
            classified_type = llm_type
        # If LLM returns UNKNOWN/OTHER and keyword also matched something low-confidence,
        # keep UNKNOWN so the bot stays silent (correct behavior)
        elif classified_type != "UNKNOWN":
            # Keep rules-based result when LLM says OTHER but rules matched something
            pass
        else:
            classified_type = "UNKNOWN"

    try:
        log.document_type = classified_type
        db.commit()
        db.refresh(log)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error while saving document classification: {str(e)}"
        )

    return classified_type


# ──────────────────────────────────────────────────────────────
# Phase 6: AI Extraction Provider Framework
# ──────────────────────────────────────────────────────────────

def parse_with_llm(
    db: Session,
    document_uuid: str
) -> dict:
    """
    Load the extracted text of the document, trigger the configured
    AI extraction provider (Gemini, Groq, or Ollama), validate the JSON,
    save the raw JSON output to disk, and transition database status to 'DONE'.

    Args:
        db            : SQLAlchemy session.
        document_uuid : UUID string of the ingested document.

    Returns:
        dict: The extracted structured data payload as a dictionary.
    """
    log = get_ingested_document(db, document_uuid)
    if not log:
        raise HTTPException(
            status_code=404,
            detail=f"Ingestion log for document UUID '{document_uuid}' not found."
        )

    # Path to raw extracted text file
    text_filename = f"{document_uuid}_extracted.txt"
    text_path = os.path.join(INGEST_FOLDER, text_filename).replace("\\", "/")

    if not os.path.exists(text_path):
        raise HTTPException(
            status_code=400,
            detail=f"Raw text extraction has not been performed for document UUID '{document_uuid}'. Run text extraction first."
        )

    try:
        with open(text_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read raw extracted text file: {str(e)}"
        )

    # Initialize configured provider
    provider = get_extraction_provider()

    # Trigger extraction
    payload = provider.extract(raw_text, document_uuid)

    # Save structured JSON output to disk parallel to text
    json_filename = f"{document_uuid}_extracted.json"
    json_path = os.path.join(INGEST_FOLDER, json_filename).replace("\\", "/")

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(payload.model_dump_json(indent=2))
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save structured JSON extraction on disk: {str(e)}"
        )

    # Update database log status to DONE
    try:
        log.processing_status = "DONE"
        db.commit()
        db.refresh(log)
    except Exception as e:
        db.rollback()
        # Clean up JSON file on database update failure
        if os.path.exists(json_path):
            os.remove(json_path)
        raise HTTPException(
            status_code=500,
            detail=f"Database error while transitioning status to DONE: {str(e)}"
        )

    return payload.model_dump()




