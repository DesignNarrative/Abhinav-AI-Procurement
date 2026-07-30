from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date, datetime

from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.rfq_award import RFQAward
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor  # noqa: F401
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.supplier import Supplier

# Imported so SQLAlchemy resolves all mappers when used standalone.
from app.models.requirement import Requirement  # noqa: F401


# Editable only while the PO is still a Draft.
DRAFT_EDITABLE = "Draft"

VALID_STATUSES = [
    "Draft", "Pending Approval", "Approved", "Sent",
    "Accepted", "Rejected", "Cancelled", "Closed"
]


class PurchaseOrderService:

    # =====================================================
    # PO number sequence (Postgres, mirrors quotation pattern)
    # =====================================================

    @staticmethod
    def _generate_po_number(db: Session) -> str:
        db.execute(text(
            "CREATE SEQUENCE IF NOT EXISTS po_number_seq START 1;"
        ))
        year = datetime.now().year
        next_val = db.execute(
            text("SELECT nextval('po_number_seq')")
        ).scalar()
        return f"PO-{year}-{next_val:04d}"

    # =====================================================
    # Create PO from an awarded quotation (one-click)
    # =====================================================

    @staticmethod
    def create_from_award(
        db: Session,
        rfq_id: int,
        created_by: str
    ) -> PurchaseOrder:

        award = db.query(RFQAward).filter(
            RFQAward.rfq_id == rfq_id
        ).first()
        if not award:
            raise ValueError(
                "This RFQ has not been awarded yet. Award a vendor first."
            )

        # Guard against duplicate PO for the same award.
        existing = db.query(PurchaseOrder).filter(
            PurchaseOrder.award_id == award.id
        ).first()
        if existing:
            raise ValueError(
                f"A Purchase Order ({existing.po_number}) already exists "
                "for this award."
            )

        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        quotation = db.query(Quotation).filter(
            Quotation.id == award.quotation_id
        ).first()
        vendor = db.query(Supplier).filter(
            Supplier.id == award.vendor_id
        ).first()

        if not quotation or not vendor:
            raise ValueError("Awarded quotation or vendor is missing.")

        po = PurchaseOrder(
            po_number=PurchaseOrderService._generate_po_number(db),
            award_id=award.id,
            rfq_id=rfq_id,
            quotation_id=quotation.id,
            vendor_id=vendor.id,
            po_date=date.today(),
            billing_address=None,
            shipping_address=rfq.delivery_location if rfq else None,
            site_name=rfq.site_name if rfq else None,
            payment_terms=quotation.payment_terms
            or (rfq.payment_terms if rfq else None),
            delivery_timeline=quotation.delivery_timeline,
            freight_total=quotation.freight_amount_total or 0.0,
            loading_unloading_total=quotation.loading_unloading_total or 0.0,
            grand_total=quotation.grand_total or 0.0,
            status="Draft",
            created_by=created_by
        )
        db.add(po)
        db.flush()

        # Snapshot each quoted item from the awarded quotation.
        quoted_items = db.query(QuotationItem).filter(
            QuotationItem.quotation_id == quotation.id,
            QuotationItem.is_quoted.is_(True)
        ).all()

        for qi in quoted_items:
            rfq_item = db.query(RFQItem).filter(
                RFQItem.id == qi.rfq_item_id
            ).first()

            po_item = PurchaseOrderItem(
                po_id=po.id,
                quotation_item_id=qi.id,
                rfq_item_id=qi.rfq_item_id,
                material_category=(
                    rfq_item.material_category if rfq_item else None
                ),
                material_name=(
                    rfq_item.material_name if rfq_item else "Item"
                ),
                ordered_quantity=(
                    qi.quoted_quantity
                    if qi.quoted_quantity is not None
                    else (rfq_item.quantity if rfq_item else 0)
                ),
                unit=rfq_item.unit if rfq_item else "Nos",
                brand=(
                    qi.brand_offered
                    or (rfq_item.brand_required if rfq_item else None)
                ),
                specs=qi.specs_offered or {},
                basic_rate=qi.basic_rate or 0.0,
                discount_percent=qi.discount_percent or 0.0,
                tax_percent=qi.tax_percent or 0.0,
                freight_amount=qi.freight_amount or 0.0,
                final_landed_rate=qi.final_landed_rate or 0.0,
                total_amount=qi.total_item_amount or 0.0,
                remarks=qi.remarks
            )
            db.add(po_item)

        db.commit()
        db.refresh(po)
        return po

    # =====================================================
    # Update PO header (only while Draft)
    # =====================================================

    @staticmethod
    def update_po(db: Session, po_id: int, data: dict) -> PurchaseOrder:
        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id
        ).first()
        if not po:
            raise ValueError("Purchase Order not found")

        if po.status != DRAFT_EDITABLE:
            raise ValueError(
                "Only Draft Purchase Orders can be edited."
            )

        editable = [
            "billing_address", "shipping_address", "site_name",
            "contact_person", "contact_number", "payment_terms",
            "delivery_timeline", "penalty_terms", "terms_conditions"
        ]
        for field in editable:
            if field in data and data[field] is not None:
                setattr(po, field, data[field])

        db.commit()
        db.refresh(po)
        return po

    # =====================================================
    # Update PO status (lifecycle)
    # =====================================================

    @staticmethod
    def update_status(
        db: Session,
        po_id: int,
        status: str,
        approved_by: str = None
    ) -> PurchaseOrder:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")

        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id
        ).first()
        if not po:
            raise ValueError("Purchase Order not found")

        po.status = status
        if status == "Approved" and approved_by:
            po.approved_by = approved_by

        db.commit()
        db.refresh(po)
        return po

    # =====================================================
    # Generate / regenerate the PO PDF
    # =====================================================

    @staticmethod
    def generate_pdf(db: Session, po_id: int) -> str:
        from app.services.po_pdf_service import generate_po_pdf

        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id
        ).first()
        if not po:
            raise ValueError("Purchase Order not found")

        items = db.query(PurchaseOrderItem).filter(
            PurchaseOrderItem.po_id == po_id
        ).order_by(PurchaseOrderItem.id.asc()).all()

        vendor = db.query(Supplier).filter(
            Supplier.id == po.vendor_id
        ).first()

        path = generate_po_pdf(po, items, vendor)
        po.pdf_path = path
        db.commit()
        db.refresh(po)
        return path

    # =====================================================
    # Send the PO to the vendor via WhatsApp (PDF document)
    # =====================================================

    @staticmethod
    def send_to_vendor(db: Session, po_id: int) -> dict:
        from app.services.whatsapp_service import send_document_message

        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id
        ).first()
        if not po:
            raise ValueError("Purchase Order not found")

        if po.status not in ("Approved", "Sent"):
            raise ValueError(
                "Only Approved Purchase Orders can be sent to the vendor."
            )

        vendor = db.query(Supplier).filter(
            Supplier.id == po.vendor_id
        ).first()
        if not vendor:
            raise ValueError("Vendor not found")

        # Ensure a PDF exists before sending.
        pdf_path = po.pdf_path
        if not pdf_path:
            pdf_path = PurchaseOrderService.generate_pdf(db, po_id)

        phone = vendor.whatsapp_number
        if not phone.startswith("+"):
            phone = f"91{phone}" if len(phone) == 10 else phone

        caption = (
            f"Purchase Order {po.po_number} from Abhinav Group. "
            "Please confirm acceptance."
        )
        filename = f"{po.po_number.replace('/', '-')}.pdf"

        result = send_document_message(
            phone_number=phone,
            file_path=pdf_path,
            filename=filename,
            caption=caption
        )

        po.whatsapp_status = "Sent"
        po.status = "Sent"
        db.commit()
        db.refresh(po)

        return {"po_number": po.po_number, "whatsapp_result": result}

    # =====================================================
    # Queries
    # =====================================================

    @staticmethod
    def get_po(db: Session, po_id: int) -> PurchaseOrder:
        return db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id
        ).first()

    @staticmethod
    def list_pos(db: Session) -> list:
        return db.query(PurchaseOrder).order_by(
            PurchaseOrder.created_at.desc()
        ).all()
