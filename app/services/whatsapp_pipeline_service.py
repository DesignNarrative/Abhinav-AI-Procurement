"""
WhatsApp Pipeline Service — Phase 11
Orchestrates the entire document intelligence pipeline for inbound WhatsApp files.
"""

import os
import shutil
import logging
from sqlalchemy.orm import Session
from fastapi import UploadFile

from app.models.supplier import Supplier
from app.models.rfq_vendor import RFQVendor
from app.models.rfq import RFQ
from app.models.document_ingestion_log import DocumentIngestionLog
from app.services.document_intelligence_service import (
    ingest_document,
    extract_text_from_pdf,
    classify_document,
    parse_with_llm
)
from app.services.entity_resolution_service import resolve_entities
from app.services.business_validation_service import validate_document_business
from app.services.quotation_draft_service import create_draft_quotation
from app.services.invoice_service import InvoiceService
from app.services.whatsapp_service import send_text_message

logger = logging.getLogger(__name__)


def process_whatsapp_document_pipeline(
    db: Session,
    sender_phone: str,
    file_path: str,
    original_filename: str
) -> dict:
    """
    Orchestrator for inbound WhatsApp documents/images from approved suppliers:
    1. Look up the supplier by phone number.
    2. Ingest the document to db/disk.
    3. Run text extraction (digital read or PaddleOCR fallback).
    4. Classify the document.
    5. If QUOTATION, run parsing, resolution, and validation.
    6. Attempt to associate with the most recent active RFQ and create a draft.
    """
    # Normalize phone numbers for lookup (e.g. remove +91 prefix or match last 10 digits)
    clean_phone = sender_phone.replace("+", "").strip()
    if clean_phone.startswith("91") and len(clean_phone) > 10:
        clean_phone_10 = clean_phone[-10:]
    else:
        clean_phone_10 = clean_phone

    # Lookup approved supplier
    supplier = db.query(Supplier).filter(
        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
        (Supplier.whatsapp_number == sender_phone)
    ).filter(
        Supplier.registration_status == "APPROVED"
    ).first()

    if not supplier:
        logger.warning(f"No approved supplier found for phone number: {sender_phone}")
        return {
            "status": "ignored",
            "reason": f"No approved supplier matches sender phone: {sender_phone}"
        }

    logger.info(f"Processing document pipeline for approved supplier: {supplier.company_name} (ID: {supplier.id})")

    # Ingest the file using a wrapper UploadFile
    # Since ingest_document expects a FastAPI UploadFile, we simulate one
    file_size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        class ShimFile:
            def __init__(self, fp):
                self.fp = fp
            def read(self, *args, **kwargs):
                return self.fp.read(*args, **kwargs)

        # Determine MIME type based on extension
        ext = os.path.splitext(original_filename)[1].lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png"
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

        from fastapi import UploadFile
        from starlette.datastructures import Headers
        import io
        
        # Read the file content bytes
        content_bytes = f.read()
        headers = Headers({"content-type": mime_type})
        
        # We need a fresh file-like object for UploadFile
        upload_file = UploadFile(
            filename=original_filename,
            file=io.BytesIO(content_bytes),
            size=file_size,
            headers=headers
        )

        # Trigger Phase 1: Ingestion
        log = ingest_document(
            db=db,
            file=upload_file,
            source="WHATSAPP",
            sender_phone=sender_phone,
            supplier_id=supplier.id
        )

    uuid = log.document_uuid
    logger.info(f"Document ingested successfully. UUID: {uuid}")

    # Run extraction -> classification -> finalization with visible failure
    # handling. Any unhandled error marks the document FAILED (instead of
    # leaving it silently stuck at PENDING) and notifies the supplier.
    try:
        # Trigger Phase 2 & 3: Extraction (digital read or Gemini vision OCR)
        extract_res = extract_text_from_pdf(db, uuid)
        logger.info(f"Text extraction completed. Requires OCR: {extract_res.get('requires_ocr')}")

        # Trigger Phase 4: Classification
        doc_type = classify_document(db, uuid)
        logger.info(f"Document classified as: {doc_type}")

        return _finalize_document(db, supplier, uuid, doc_type, sender_phone)
    except Exception as pipeline_err:
        return _mark_failed(db, sender_phone, supplier, uuid, pipeline_err)


def _finalize_document(
    db: Session,
    supplier: Supplier,
    uuid: str,
    doc_type: str,
    sender_phone: str
) -> dict:
    """
    Shared post-classification pipeline used by both the document/image path
    and the plain-text quotation path:
      - Non QUOTATION/INVOICE  -> notify + stop.
      - Parse (LLM) -> resolve entities -> business validation.
      - INVOICE  -> create invoice record.
      - QUOTATION-> link most-recent active RFQ and create a draft.
    Raises on unrecoverable extraction/parse errors so the caller can mark the
    document FAILED. Invoice/draft creation keep their own soft error handling.
    """
    if doc_type not in ["QUOTATION", "INVOICE"]:
        logger.info(f"Document UUID {uuid} classified as {doc_type}, not QUOTATION or INVOICE. Skipping extraction parsing.")
        send_text_message(
            sender_phone,
            f"Dear {supplier.contact_person_name},\n\n"
            f"Thank you for sending your document. We classified this document as a {doc_type}. "
            f"Please note that only Quotation and Invoice files are processed automatically. "
            f"Our procurement team will review this manually if necessary."
        )
        return {
            "status": "processed",
            "document_uuid": uuid,
            "document_type": doc_type,
            "action": "none_not_quotation"
        }

    # Trigger Phase 6: Parse with LLM
    logger.info(f"Running LLM parsing for {doc_type} UUID: {uuid}")
    parse_with_llm(db, uuid)

    # Trigger Phase 7: Entity Resolution
    logger.info(f"Running Entity Resolution for {doc_type} UUID: {uuid}")
    resolve_entities(db, uuid)

    # Trigger Phase 8: Business Validation
    logger.info(f"Running Business Validation for {doc_type} UUID: {uuid}")
    validate_document_business(db, uuid)

    # INVOICE branch: capture the invoice record instead of drafting a
    # quotation. Keeps the quotation path below completely unchanged.
    if doc_type == "INVOICE":
        logger.info(f"Document UUID {uuid} is an INVOICE. Creating invoice record...")
        try:
            invoice = InvoiceService.create_from_extraction(
                db=db,
                document_uuid=uuid,
                vendor_id=supplier.id,
                created_by="AI_SYSTEM"
            )
            send_text_message(
                sender_phone,
                f"Dear {supplier.contact_person_name},\n\n"
                f"Thank you! Your invoice {invoice.invoice_number} has been "
                f"received and recorded. Our accounts team will verify it "
                f"against the purchase order and process payment."
            )
            return {
                "status": "processed",
                "document_uuid": uuid,
                "document_type": doc_type,
                "action": "invoice_created",
                "invoice_id": invoice.id
            }
        except Exception as inv_err:
            logger.error(f"Error creating invoice: {str(inv_err)}", exc_info=True)
            db.rollback()
            send_text_message(
                sender_phone,
                f"Dear {supplier.contact_person_name},\n\n"
                f"We received your invoice document but could not record it "
                f"automatically. Our accounts team will process it manually."
            )
            return {
                "status": "processed",
                "document_uuid": uuid,
                "document_type": doc_type,
                "action": "manual_review_invoice_error",
                "error": str(inv_err)
            }

    # Trigger Phase 9: Auto-Drafting to DB if active RFQ is resolved
    # Find most recent active RFQ Vendor association
    rfq_vendor = db.query(RFQVendor).join(RFQ).filter(
        RFQVendor.vendor_id == supplier.id,
        RFQ.status.notin_(["Closed", "Cancelled"])
    ).order_by(RFQ.created_at.desc()).first()

    if rfq_vendor:
        rfq = rfq_vendor.rfq
        logger.info(f"Found active RFQ {rfq.rfq_number} (ID: {rfq.id}) for vendor. Triggering auto-draft...")
        try:
            draft_res = create_draft_quotation(db, uuid, rfq.id)
            logger.info(f"Auto-draft quotation created successfully. ID: {draft_res.get('quotation_id')}")

            # Send success WhatsApp message to supplier
            send_text_message(
                sender_phone,
                f"Dear {supplier.contact_person_name},\n\n"
                f"Thank you! Your quotation for RFQ {rfq.rfq_number} has been received and processed successfully. "
                f"A draft quotation has been generated for our procurement team's review."
            )
            return {
                "status": "processed",
                "document_uuid": uuid,
                "document_type": doc_type,
                "action": "draft_created",
                "rfq_id": rfq.id,
                "quotation_id": draft_res.get("quotation_id")
            }
        except Exception as draft_err:
            logger.error(f"Error creating draft quotation: {str(draft_err)}", exc_info=True)
            db.rollback()
            # Send warning/manual-review WhatsApp message to supplier
            send_text_message(
                sender_phone,
                f"Dear {supplier.contact_person_name},\n\n"
                f"We received your quotation document and extracted the details, but could not automatically "
                f"draft it into our system due to a validation warning. Our procurement team will review it manually."
            )
            return {
                "status": "processed",
                "document_uuid": uuid,
                "document_type": doc_type,
                "action": "manual_review_draft_error",
                "error": str(draft_err)
            }
    else:
        logger.info(f"No active RFQ found for vendor. Processing stops at extraction phase.")
        # Send confirmation WhatsApp message to supplier
        send_text_message(
            sender_phone,
            f"Dear {supplier.contact_person_name},\n\n"
            f"We have received your quotation document and processed it. "
            f"However, we could not find an active Request for Quotation (RFQ) associated with your profile. "
            f"Our team will review your quote manually."
        )
        return {
            "status": "processed",
            "document_uuid": uuid,
            "document_type": doc_type,
            "action": "manual_review_no_rfq"
        }


def _mark_failed(
    db: Session,
    sender_phone: str,
    supplier: Supplier,
    uuid: str,
    error: Exception
) -> dict:
    """
    Record an unrecoverable pipeline failure so it is visible on the dashboard
    (status FAILED + processing_error) and always reply to the supplier — never
    leave a document silently stuck at PENDING.
    """
    logger.error(f"Pipeline failed for document UUID {uuid}: {str(error)}", exc_info=True)
    try:
        db.rollback()
    except Exception:
        pass

    try:
        log = db.query(DocumentIngestionLog).filter(
            DocumentIngestionLog.document_uuid == uuid
        ).first()
        if log:
            log.processing_status = "FAILED"
            log.processing_error = str(error)[:500]
            db.commit()
    except Exception as db_err:
        logger.error(f"Failed to persist FAILED status for {uuid}: {str(db_err)}", exc_info=True)
        db.rollback()

    try:
        contact = supplier.contact_person_name if supplier else "Supplier"
        send_text_message(
            sender_phone,
            f"Dear {contact},\n\n"
            f"We received your document but our system could not read it automatically. "
            f"Our procurement team has been notified and will review it manually. "
            f"Thank you for your patience."
        )
    except Exception:
        pass

    return {
        "status": "failed",
        "document_uuid": uuid,
        "action": "marked_failed",
        "error": str(error)
    }


def process_whatsapp_text_quotation(
    db: Session,
    sender_phone: str,
    message_text: str
) -> dict:
    """
    Handle a plain-text WhatsApp quotation from an approved supplier.

    The message text is treated as the already-extracted document text, so the
    OCR/PDF stages are skipped. It is logged as a DocumentIngestionLog (a .txt
    pseudo-document), classified, and — if it is a QUOTATION/INVOICE — pushed
    through the same finalization pipeline as file uploads.
    """
    import hashlib
    import uuid as uuid_lib
    from app.services.document_intelligence_service import (
        INGEST_FOLDER,
        _ensure_ingest_folder,
        classify_document,
    )

    # Normalize phone numbers for lookup (mirror the document pipeline).
    clean_phone = sender_phone.replace("+", "").strip()
    if clean_phone.startswith("91") and len(clean_phone) > 10:
        clean_phone_10 = clean_phone[-10:]
    else:
        clean_phone_10 = clean_phone

    supplier = db.query(Supplier).filter(
        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
        (Supplier.whatsapp_number == sender_phone)
    ).filter(
        Supplier.registration_status == "APPROVED"
    ).first()

    if not supplier:
        logger.warning(f"No approved supplier found for text quotation from: {sender_phone}")
        return {
            "status": "ignored",
            "reason": f"No approved supplier matches sender phone: {sender_phone}"
        }

    _ensure_ingest_folder()

    text_bytes = message_text.encode("utf-8")
    file_hash = hashlib.sha256(text_bytes).hexdigest()

    # Deduplicate identical text messages.
    existing = db.query(DocumentIngestionLog).filter(
        DocumentIngestionLog.file_hash == file_hash
    ).first()
    if existing:
        doc_uuid = existing.document_uuid
        log = existing
    else:
        doc_uuid = str(uuid_lib.uuid4())
        stored_filename = f"{doc_uuid}.txt"
        file_path = os.path.join(INGEST_FOLDER, stored_filename).replace("\\", "/")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(message_text)
        log = DocumentIngestionLog(
            document_uuid=doc_uuid,
            original_filename="whatsapp_text_quotation.txt",
            stored_filename=stored_filename,
            file_path=file_path,
            file_hash=file_hash,
            file_size_bytes=len(text_bytes),
            mime_type="text/plain",
            file_extension=".txt",
            source="WHATSAPP",
            sender_phone=sender_phone,
            supplier_id=supplier.id,
            document_type=None,
            processing_status="PENDING",
            processing_error=None
        )
        db.add(log)
        db.commit()
        db.refresh(log)

    logger.info(f"Text quotation ingested. UUID: {doc_uuid}")

    try:
        # The message text IS the extracted text: write it where the pipeline
        # expects it so classify/parse read it directly (no OCR/PDF stage).
        text_path = os.path.join(INGEST_FOLDER, f"{doc_uuid}_extracted.txt").replace("\\", "/")
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(message_text)

        log.processing_status = "PROCESSING"
        db.commit()

        doc_type = classify_document(db, doc_uuid)
        logger.info(f"Text quotation classified as: {doc_type}")

        return _finalize_document(db, supplier, doc_uuid, doc_type, sender_phone)
    except Exception as pipeline_err:
        return _mark_failed(db, sender_phone, supplier, doc_uuid, pipeline_err)
