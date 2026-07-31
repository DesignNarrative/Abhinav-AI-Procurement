import os
from datetime import date
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException
from rapidfuzz import fuzz

from app.schemas.document_extraction import DocumentExtractionPayload
from app.services.document_intelligence_service import INGEST_FOLDER, get_ingested_document
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.supplier import Supplier
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.document_ingestion_log import DocumentIngestionLog
from dateutil.parser import parse as parse_date


def _get_field_value(field, default=None):
    """Safely extract .value from an ExtractedField, or return default."""
    if field is None:
        return default
    v = getattr(field, "value", None)
    return v if v is not None else default


def create_draft_quotation(
    db: Session,
    document_uuid: str,
    rfq_id: int,
    created_by: str = "AI_SYSTEM",
    fuzzy_threshold: float = 80.0,
) -> dict:
    """
    Auto-draft a Quotation and QuotationItems from a validated/resolved
    extraction JSON staging file.

    Args:
        db:               SQLAlchemy session.
        document_uuid:    UUID of the ingested document.
        rfq_id:           The RFQ ID this quotation belongs to.
        created_by:       Username / identifier to stamp on created_by field.
        fuzzy_threshold:  Minimum similarity % to match line items to RFQ items.

    Returns:
        A dict containing the newly created quotation ID and line item count.
    """

    # ── 0. Load & validate the ingested document record ───────────────────────
    log = get_ingested_document(db, document_uuid)
    if not log:
        raise HTTPException(
            status_code=404,
            detail=f"Ingestion log for document UUID '{document_uuid}' not found."
        )

    json_path = os.path.join(INGEST_FOLDER, f"{document_uuid}_extracted.json").replace("\\", "/")
    if not os.path.exists(json_path):
        raise HTTPException(
            status_code=400,
            detail=f"No extraction JSON file found for UUID '{document_uuid}'. "
                   f"Run /parse and /validate first."
        )

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            payload: DocumentExtractionPayload = DocumentExtractionPayload.model_validate_json(f.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse extraction JSON: {e}")

    # ── 1. Resolve the RFQ ────────────────────────────────────────────────────
    log_record = db.query(DocumentIngestionLog).filter(
        DocumentIngestionLog.document_uuid == document_uuid
    ).first()

    from app.models.rfq_vendor import RFQVendor  # ensure registry loaded
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ with ID {rfq_id} not found.")

    rfq_items: list[RFQItem] = db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()
    if not rfq_items:
        raise HTTPException(
            status_code=400,
            detail=f"RFQ {rfq_id} has no line items. Cannot map quotation items."
        )

    # ── 2. Resolve the Supplier (vendor) ─────────────────────────────────────
    supplier_code = _get_field_value(payload.vendor_metadata.supplier_code)
    extracted_gst = _get_field_value(payload.vendor_metadata.gst_number)
    extracted_vendor_name = _get_field_value(payload.vendor_metadata.vendor_name)

    supplier: Optional[Supplier] = None

    # Try authenticated supplier from ingestion log first
    if log_record and log_record.supplier_id:
        supplier = db.query(Supplier).filter(Supplier.id == log_record.supplier_id).first()

    # Try exact supplier_code second
    if not supplier and supplier_code:
        supplier = db.query(Supplier).filter(Supplier.supplier_code == str(supplier_code)).first()

    # Try exact GST match
    if not supplier and extracted_gst:
        supplier = db.query(Supplier).filter(Supplier.gst_number == extracted_gst).first()

    # Fuzzy company name match as last resort
    if not supplier and extracted_vendor_name:
        all_suppliers = db.query(Supplier).all()
        best_score = 0.0
        for s in all_suppliers:
            score = fuzz.token_sort_ratio(extracted_vendor_name.lower(), s.company_name.lower())
            if score > best_score:
                best_score = score
                supplier = s
        if best_score < fuzzy_threshold:
            supplier = None

    if not supplier:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not resolve vendor to a supplier in the database. "
                f"Extracted vendor name: '{extracted_vendor_name}', GST: '{extracted_gst}'. "
                f"Please add/map this vendor first, then retry."
            )
        )

    # ── 3. Check for duplicate quotation (idempotency guard) ──────────────────
    extracted_doc_number = _get_field_value(payload.document_metadata.document_number)
    # Build a quotation number: use the extracted doc number, or generate one
    quotation_number = (
        extracted_doc_number
        if extracted_doc_number
        else f"AI-DRAFT-{document_uuid[:8].upper()}"
    )

    existing = db.query(Quotation).filter(
        Quotation.quotation_number == quotation_number,
        Quotation.rfq_id == rfq_id,
    ).first()
    if existing:
        return {
            "message": "Quotation already exists for this document UUID and RFQ.",
            "quotation_id": existing.id,
            "quotation_number": existing.quotation_number,
            "line_items_created": 0,
            "duplicate": True,
        }

    # ── 3b. Revision handling: supersede this vendor's previous latest quote ──
    # A different quotation number for the same vendor + RFQ is a revision:
    # every older quote loses is_latest so comparison always shows exactly one
    # column per vendor (the most recent quote).
    superseded_rows = db.query(Quotation).filter(
        Quotation.rfq_id == rfq_id,
        Quotation.vendor_id == supplier.id,
        Quotation.is_latest == True,  # noqa: E712
    ).all()
    revision_number = 0
    superseded = None
    if superseded_rows:
        revision_number = max((q.revision_number or 0) for q in superseded_rows) + 1
        for old_q in superseded_rows:
            old_q.is_latest = False
        superseded = max(superseded_rows, key=lambda q: q.id)

    # ── 4. Parse quotation header fields ──────────────────────────────────────
    raw_date = _get_field_value(payload.document_metadata.document_date)
    try:
        date_received = parse_date(str(raw_date)).date() if raw_date else date.today()
    except Exception:
        date_received = date.today()

    grand_total_val = _get_field_value(payload.commercial_metadata.grand_total_amount, 0.0)
    payment_terms_val = _get_field_value(payload.commercial_metadata.payment_terms)
    delivery_terms_val = _get_field_value(payload.commercial_metadata.delivery_terms)
    freight_val = _get_field_value(payload.commercial_metadata.total_freight_amount, 0.0)

    # ── 5. Create the Quotation header record ─────────────────────────────────
    quotation = Quotation(
        quotation_number=quotation_number,
        revision_number=revision_number,
        rfq_id=rfq_id,
        vendor_id=supplier.id,
        is_latest=True,
        date_received=date_received,
        validity_date=None,
        payment_terms=payment_terms_val,
        delivery_timeline=delivery_terms_val,
        freight_amount_total=float(freight_val) if freight_val else 0.0,
        loading_unloading_total=0.0,
        grand_total=float(grand_total_val) if grand_total_val else 0.0,
        attachment_path=log.file_path if hasattr(log, "file_path") else None,
        status="Draft",
        creation_source="AI_EXTRACTED",
        created_by=created_by,
    )
    db.add(quotation)
    db.flush()  # Get quotation.id before committing

    # ── 6. Create QuotationItem records ───────────────────────────────────────
    items_created = 0
    unmatched_items = []

    for ext_item in payload.line_items:
        ext_name = _get_field_value(ext_item.material_name, "")

        # Fuzzy match against RFQ items. token_set_ratio handles subset names
        # (e.g. RFQ "tmt bar" vs quoted "TMT BAR (Grade 550e)") that
        # token_sort_ratio would under-score.
        best_score = 0.0
        best_rfq_item: Optional[RFQItem] = None
        for ri in rfq_items:
            score = fuzz.token_set_ratio(ext_name.lower(), ri.material_name.lower())
            if score > best_score:
                best_score = score
                best_rfq_item = ri

        if best_rfq_item is None or best_score < fuzzy_threshold:
            # No confident match against this RFQ's items: skip the item
            # instead of force-mapping it to rfq_items[0], which would pollute
            # another material's comparison row with the wrong rate.
            unmatched_items.append(ext_name)
            continue

        qty = _get_field_value(ext_item.quantity, 0.0)
        rate = _get_field_value(ext_item.basic_rate, 0.0)
        discount = _get_field_value(ext_item.discount_percent, 0.0)
        tax = _get_field_value(ext_item.tax_percent, 0.0)
        total = _get_field_value(ext_item.total_item_amount, 0.0)

        # Calculate final landed rate
        taxable = float(rate) * (1 - float(discount) / 100.0)
        landed = taxable * (1 + float(tax) / 100.0)

        q_item = QuotationItem(
            quotation_id=quotation.id,
            rfq_item_id=best_rfq_item.id,
            is_quoted=True,
            quoted_quantity=float(qty) if qty else None,
            brand_offered=_get_field_value(ext_item.offered_brand, None),
            specs_offered={},
            basic_rate=float(rate) if rate else 0.0,
            discount_percent=float(discount) if discount else 0.0,
            tax_percent=float(tax) if tax else 0.0,
            freight_amount=0.0,
            final_landed_rate=round(landed, 3),
            total_item_amount=float(total) if total else 0.0,
            remarks=_get_field_value(ext_item.remarks, None),
        )
        db.add(q_item)
        items_created += 1

    db.commit()
    db.refresh(quotation)

    message = "Draft quotation created successfully from AI extraction."
    if unmatched_items:
        message += (
            f" Note: {len(unmatched_items)} extracted item(s) did not match any "
            f"RFQ item and were left unmapped: {', '.join(unmatched_items)}."
        )

    return {
        "message": message,
        "quotation_id": quotation.id,
        "quotation_number": quotation.quotation_number,
        "vendor_name": supplier.company_name,
        "vendor_id": supplier.id,
        "rfq_id": rfq_id,
        "line_items_created": items_created,
        "unmatched_items": unmatched_items,
        "grand_total": float(quotation.grand_total),
        "status": quotation.status,
        "duplicate": False,
        "revision_number": quotation.revision_number,
        "superseded_quotation_id": superseded.id if superseded else None,
    }
