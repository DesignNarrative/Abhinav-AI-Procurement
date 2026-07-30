from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.invoice import Invoice
from app.models.invoice_item import InvoiceItem
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier import Supplier

# Resolve mappers when the service is used standalone.
from app.models.delivery import Delivery  # noqa: F401
from app.models.delivery_item import DeliveryItem  # noqa: F401
from app.models.quotation import Quotation  # noqa: F401
from app.models.quotation_item import QuotationItem  # noqa: F401
from app.models.rfq import RFQ  # noqa: F401
from app.models.rfq_item import RFQItem  # noqa: F401
from app.models.rfq_vendor import RFQVendor  # noqa: F401
from app.models.rfq_award import RFQAward  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401

from app.services.delivery_service import DeliveryService


VALID_STATUSES = [
    "Received", "Verified", "Mismatch", "Approved", "Paid"
]

# Tolerance for rounding differences when comparing money / quantities.
QTY_TOLERANCE = 0.001
RATE_TOLERANCE = 0.01
AMOUNT_TOLERANCE = 1.0


class InvoiceService:

    # =====================================================
    # Create an invoice (manual or from the document pipeline)
    # =====================================================

    @staticmethod
    def create_invoice(db: Session, data: dict) -> Invoice:
        vendor_id = data.get("vendor_id")
        vendor = db.query(Supplier).filter(
            Supplier.id == vendor_id
        ).first()
        if not vendor:
            raise ValueError("Vendor not found")

        invoice_number = (data.get("invoice_number") or "").strip()
        if not invoice_number:
            raise ValueError("Invoice number is required")

        po_id = data.get("po_id")
        if po_id is not None:
            po = db.query(PurchaseOrder).filter(
                PurchaseOrder.id == po_id
            ).first()
            if not po:
                raise ValueError("Purchase Order not found")

        # Duplicate invoice number detection (same vendor).
        dup = db.query(Invoice).filter(
            Invoice.vendor_id == vendor_id,
            func.lower(Invoice.invoice_number) == invoice_number.lower()
        ).first()
        if dup:
            raise ValueError(
                f"Invoice number '{invoice_number}' already exists for "
                f"this vendor (invoice #{dup.id})."
            )

        invoice = Invoice(
            po_id=po_id,
            vendor_id=vendor_id,
            document_uuid=data.get("document_uuid"),
            invoice_number=invoice_number,
            invoice_date=data.get("invoice_date"),
            taxable_amount=data.get("taxable_amount", 0) or 0,
            cgst_amount=data.get("cgst_amount", 0) or 0,
            sgst_amount=data.get("sgst_amount", 0) or 0,
            igst_amount=data.get("igst_amount", 0) or 0,
            total_tax_amount=data.get("total_tax_amount", 0) or 0,
            freight_amount=data.get("freight_amount", 0) or 0,
            invoice_amount=data.get("invoice_amount", 0) or 0,
            file_path=data.get("file_path"),
            status="Received",
            match_status="Not Checked",
            created_by=data["created_by"]
        )
        db.add(invoice)
        db.flush()

        for row in data.get("items", []) or []:
            db.add(InvoiceItem(
                invoice_id=invoice.id,
                po_item_id=row.get("po_item_id"),
                material_name=row.get("material_name") or "Item",
                unit=row.get("unit"),
                invoiced_quantity=row.get("invoiced_quantity", 0) or 0,
                rate=row.get("rate", 0) or 0,
                tax_percent=row.get("tax_percent", 0) or 0,
                amount=row.get("amount", 0) or 0,
                remarks=row.get("remarks")
            ))

        db.commit()
        db.refresh(invoice)
        return invoice

    # =====================================================
    # 3-way match: Invoice vs PO vs GRN
    # =====================================================

    @staticmethod
    def run_three_way_match(db: Session, invoice_id: int) -> dict:
        """
        Compares the invoice against the PO snapshot and the GRN receipt
        summary. Returns a structured result and persists match_status /
        match_notes on the invoice. Never auto-approves — a mismatch simply
        flags the invoice for human review.
        """
        invoice = db.query(Invoice).filter(
            Invoice.id == invoice_id
        ).first()
        if not invoice:
            raise ValueError("Invoice not found")

        if not invoice.po_id:
            invoice.match_status = "Not Checked"
            invoice.match_notes = (
                "No Purchase Order linked — 3-way match not possible."
            )
            db.commit()
            db.refresh(invoice)
            return {
                "invoice_id": invoice.id,
                "match_status": invoice.match_status,
                "issues": [invoice.match_notes],
                "lines": []
            }

        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == invoice.po_id
        ).first()

        po_items = db.query(PurchaseOrderItem).filter(
            PurchaseOrderItem.po_id == invoice.po_id
        ).all()
        po_item_by_id = {pi.id: pi for pi in po_items}

        # Received quantities from the GRN receipt summary.
        receipt = DeliveryService.get_po_receipt_summary(db, invoice.po_id)
        received_by_item = {
            r["po_item_id"]: r["received_quantity"] for r in receipt
        }

        inv_items = db.query(InvoiceItem).filter(
            InvoiceItem.invoice_id == invoice.id
        ).all()

        issues = []
        lines = []

        # Line-level checks (only where the invoice line maps to a PO item).
        for ii in inv_items:
            line = {
                "material_name": ii.material_name,
                "invoiced_quantity": float(ii.invoiced_quantity or 0),
                "rate": float(ii.rate or 0),
                "po_item_id": ii.po_item_id,
                "checks": []
            }
            pi = po_item_by_id.get(ii.po_item_id) if ii.po_item_id else None
            if not pi:
                line["checks"].append("Not matched to a PO line")
                issues.append(
                    f"'{ii.material_name}' not linked to any PO item."
                )
                lines.append(line)
                continue

            po_rate = float(pi.final_landed_rate or 0)
            inv_rate = float(ii.rate or 0)
            if abs(po_rate - inv_rate) > RATE_TOLERANCE:
                msg = (
                    f"Rate mismatch on '{ii.material_name}': "
                    f"PO ₹{po_rate:.2f} vs Invoice ₹{inv_rate:.2f}"
                )
                line["checks"].append(msg)
                issues.append(msg)

            ordered_qty = float(pi.ordered_quantity or 0)
            inv_qty = float(ii.invoiced_quantity or 0)
            if inv_qty - ordered_qty > QTY_TOLERANCE:
                msg = (
                    f"Over-billed qty on '{ii.material_name}': "
                    f"invoiced {inv_qty} > ordered {ordered_qty}"
                )
                line["checks"].append(msg)
                issues.append(msg)

            received_qty = float(received_by_item.get(pi.id, 0))
            if inv_qty - received_qty > QTY_TOLERANCE:
                msg = (
                    f"Invoiced more than received on '{ii.material_name}': "
                    f"invoiced {inv_qty} > received {received_qty}"
                )
                line["checks"].append(msg)
                issues.append(msg)

            if not line["checks"]:
                line["checks"].append("OK")
            lines.append(line)

        # Header-level total check against the PO grand total.
        po_total = float(po.grand_total or 0) if po else 0
        inv_total = float(invoice.invoice_amount or 0)
        if po_total > 0 and inv_total - po_total > AMOUNT_TOLERANCE:
            issues.append(
                f"Invoice total ₹{inv_total:.2f} exceeds PO total "
                f"₹{po_total:.2f}"
            )

        match_status = "Mismatch" if issues else "Matched"
        invoice.match_status = match_status
        invoice.match_notes = (
            "; ".join(issues) if issues else "All checks passed."
        )
        if match_status == "Matched" and invoice.status == "Received":
            invoice.status = "Verified"
        elif match_status == "Mismatch":
            invoice.status = "Mismatch"

        db.commit()
        db.refresh(invoice)

        return {
            "invoice_id": invoice.id,
            "match_status": match_status,
            "issues": issues,
            "lines": lines
        }

    # =====================================================
    # Create an invoice from a document-intelligence extraction
    # =====================================================

    @staticmethod
    def create_from_extraction(
        db: Session,
        document_uuid: str,
        vendor_id: int,
        created_by: str = "AI_SYSTEM"
    ) -> Invoice:
        """
        Builds an invoice record from the staged extraction JSON produced by
        the document-intelligence pipeline (same JSON that feeds the
        quotation auto-draft). Best-effort links the most recent open PO for
        the vendor; the 3-way match can be run afterwards from the UI.
        """
        import os
        from dateutil.parser import parse as parse_date

        from app.schemas.document_extraction import DocumentExtractionPayload
        from app.services.document_intelligence_service import INGEST_FOLDER

        json_path = os.path.join(
            INGEST_FOLDER, f"{document_uuid}_extracted.json"
        ).replace("\\", "/")
        if not os.path.exists(json_path):
            raise ValueError(
                f"No extraction JSON found for document '{document_uuid}'."
            )
        with open(json_path, "r", encoding="utf-8") as f:
            payload = DocumentExtractionPayload.model_validate_json(f.read())

        def _val(field, default=None):
            if field is None:
                return default
            v = getattr(field, "value", None)
            return v if v is not None else default

        meta = payload.document_metadata
        comm = payload.commercial_metadata

        invoice_number = _val(meta.document_number) or f"AUTO-{document_uuid[:8]}"

        invoice_date = None
        raw_date = _val(meta.document_date)
        if raw_date:
            try:
                invoice_date = parse_date(str(raw_date), dayfirst=True).date()
            except Exception:
                invoice_date = None

        # Best-effort link to the latest open PO for this vendor.
        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.vendor_id == vendor_id,
            PurchaseOrder.status.notin_(["Cancelled", "Draft"])
        ).order_by(PurchaseOrder.created_at.desc()).first()

        items = []
        po_items = []
        if po:
            po_items = db.query(PurchaseOrderItem).filter(
                PurchaseOrderItem.po_id == po.id
            ).all()

        from rapidfuzz import fuzz

        for li in payload.line_items:
            name = _val(li.material_name) or "Item"
            po_item_id = None
            if po_items:
                best = None
                best_score = 0
                for pi in po_items:
                    score = fuzz.token_sort_ratio(
                        name.lower(), (pi.material_name or "").lower()
                    )
                    if score > best_score:
                        best_score = score
                        best = pi
                if best and best_score >= 80:
                    po_item_id = best.id
            items.append({
                "po_item_id": po_item_id,
                "material_name": name,
                "unit": _val(li.unit_of_measure),
                "invoiced_quantity": _val(li.quantity, 0) or 0,
                "rate": (
                    _val(li.final_landed_rate)
                    or _val(li.basic_rate, 0)
                    or 0
                ),
                "tax_percent": _val(li.tax_percent, 0) or 0,
                "amount": _val(li.total_item_amount, 0) or 0
            })

        data = {
            "vendor_id": vendor_id,
            "po_id": po.id if po else None,
            "document_uuid": document_uuid,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "taxable_amount": _val(comm.total_basic_amount, 0) or 0,
            "total_tax_amount": _val(comm.total_tax_amount, 0) or 0,
            "freight_amount": _val(comm.total_freight_amount, 0) or 0,
            "invoice_amount": _val(comm.grand_total_amount, 0) or 0,
            "created_by": created_by,
            "items": items
        }
        return InvoiceService.create_invoice(db, data)

    # =====================================================
    # Status update (approve, mark paid, etc.)
    # =====================================================

    @staticmethod
    def update_status(
        db: Session,
        invoice_id: int,
        status: str,
        approved_by: str = None
    ) -> Invoice:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")

        invoice = db.query(Invoice).filter(
            Invoice.id == invoice_id
        ).first()
        if not invoice:
            raise ValueError("Invoice not found")

        invoice.status = status
        if status == "Approved" and approved_by:
            invoice.approved_by = approved_by

        db.commit()
        db.refresh(invoice)
        return invoice

    # =====================================================
    # Queries
    # =====================================================

    @staticmethod
    def get_invoice(db: Session, invoice_id: int) -> Invoice:
        return db.query(Invoice).filter(
            Invoice.id == invoice_id
        ).first()

    @staticmethod
    def list_invoices(db: Session) -> list:
        return db.query(Invoice).order_by(
            Invoice.created_at.desc()
        ).all()

    @staticmethod
    def serialize(db: Session, invoice: Invoice) -> dict:
        vendor = db.query(Supplier).filter(
            Supplier.id == invoice.vendor_id
        ).first()
        po = None
        if invoice.po_id:
            po = db.query(PurchaseOrder).filter(
                PurchaseOrder.id == invoice.po_id
            ).first()
        return {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": (
                invoice.invoice_date.isoformat()
                if invoice.invoice_date else None
            ),
            "vendor_id": invoice.vendor_id,
            "vendor_name": vendor.company_name if vendor else None,
            "po_id": invoice.po_id,
            "po_number": po.po_number if po else None,
            "invoice_amount": float(invoice.invoice_amount or 0),
            "total_tax_amount": float(invoice.total_tax_amount or 0),
            "status": invoice.status,
            "match_status": invoice.match_status,
            "match_notes": invoice.match_notes,
            "created_at": invoice.created_at.isoformat()
        }
