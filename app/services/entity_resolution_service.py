import os
import json
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.document_ingestion_log import DocumentIngestionLog
from app.models.supplier import Supplier
from app.schemas.document_extraction import DocumentExtractionPayload, ExtractedString, ValidationLogEntry
from app.services.document_intelligence_service import INGEST_FOLDER, get_ingested_document
from rapidfuzz import fuzz

def resolve_entities(db: Session, document_uuid: str, threshold: float = 80.0) -> dict:
    """
    Perform entity resolution on the extracted quotation data:
    1. Resolve vendor to database 'suppliers' table using GST (exact) or company name (fuzzy).
    Overwrites the staging JSON file on disk and returns the updated resolved dict.
    """
    log = get_ingested_document(db, document_uuid)
    if not log:
        raise HTTPException(
            status_code=404,
            detail=f"Ingestion log for document UUID '{document_uuid}' not found."
        )

    json_filename = f"{document_uuid}_extracted.json"
    json_path = os.path.join(INGEST_FOLDER, json_filename).replace("\\", "/")

    if not os.path.exists(json_path):
        raise HTTPException(
            status_code=400,
            detail=f"Structured JSON extraction output does not exist for UUID '{document_uuid}'. Trigger extraction/parse first."
        )

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            raw_json = f.read()
        payload = DocumentExtractionPayload.model_validate_json(raw_json)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read/parse existing extraction JSON file: {str(e)}"
        )

    # 1. Resolve Vendor
    resolved_supplier = None
    gst_field = payload.vendor_metadata.gst_number
    gst_val = gst_field.value if gst_field else None

    # Try exact GST match first
    if gst_val:
        cleaned_gst = gst_val.strip().upper()
        supplier_match = db.query(Supplier).filter(
            Supplier.gst_number.ilike(cleaned_gst)
        ).first()
        if supplier_match:
            resolved_supplier = supplier_match
            evidence_msg = f"Exact GST match: {gst_val}"
            confidence_score = 1.0

    # If not matched by GST, run fuzzy string match on vendor name
    extracted_vendor = payload.vendor_metadata.vendor_name.value if payload.vendor_metadata.vendor_name else None
    if not resolved_supplier and extracted_vendor:
        all_suppliers = db.query(Supplier).all()
        best_score = 0.0
        best_supplier = None
        
        for s in all_suppliers:
            score = fuzz.token_sort_ratio(extracted_vendor.lower(), s.company_name.lower())
            if score > best_score:
                best_score = score
                best_supplier = s
                
        if best_supplier and best_score >= threshold:
            resolved_supplier = best_supplier
            evidence_msg = f"Fuzzy company name match: '{best_supplier.company_name}' with score {best_score:.1f}%"
            confidence_score = best_score / 100.0

    # Apply resolved vendor details to payload
    if resolved_supplier:
        method = "rapidfuzz-token-sort"
        payload.vendor_metadata.supplier_code = ExtractedString(
            value=resolved_supplier.supplier_code or f"SUP_{resolved_supplier.id}",
            confidence=confidence_score,
            evidence=evidence_msg,
            page_number=payload.vendor_metadata.vendor_name.page_number if payload.vendor_metadata.vendor_name else 1,
            extraction_method=method,
            validation_status="PASSED"
        )
        report = payload.validation_summary.semantic_validation
        report.status = "PASSED"
        
        def get_rule_name(l):
            if isinstance(l, dict):
                return l.get("rule_name")
            return getattr(l, "rule_name", None)

        # Avoid duplicate validation entries
        report.logs = [log for log in report.logs if get_rule_name(log) != "vendor_entity_resolution"]
        report.logs.append(ValidationLogEntry(
            rule_name="vendor_entity_resolution",
            status="PASSED",
            message=f"Successfully resolved vendor to supplier '{resolved_supplier.company_name}' ({resolved_supplier.supplier_code or resolved_supplier.id})."
        ))

    # Save resolved payload back to disk
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(payload.model_dump_json(indent=2))
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save resolved JSON file back to disk: {str(e)}"
        )

    return payload.model_dump()
