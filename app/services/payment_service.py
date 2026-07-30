import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.models.supplier import Supplier

# Resolve mappers when used standalone.
from app.models.invoice_item import InvoiceItem  # noqa: F401
from app.models.quotation import Quotation  # noqa: F401
from app.models.rfq import RFQ  # noqa: F401
from app.models.rfq_vendor import RFQVendor  # noqa: F401
from app.models.rfq_award import RFQAward  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401


VALID_TYPES = ["Advance", "50%", "Full", "Credit", "Part"]
VALID_STATUSES = ["Pending", "Due", "Overdue", "Partial", "Paid"]

# Window (in days) within which a pending payment is considered "Due"
# rather than merely "Pending".
DUE_SOON_WINDOW = 3


class PaymentService:

    # =====================================================
    # Credit-days parsing from free-text payment terms
    # =====================================================

    @staticmethod
    def parse_credit_days(payment_terms: str) -> int:
        """
        Extracts the credit period (in days) from free-text payment terms
        such as "30 days", "Net 45", "Credit 60 days". Returns 0 when no
        number is found (treated as immediate / advance).
        """
        if not payment_terms:
            return 0
        match = re.search(r"(\d{1,3})", str(payment_terms))
        if not match:
            return 0
        return int(match.group(1))

    @staticmethod
    def compute_due_date(
        base_date: date,
        payment_terms: str
    ) -> date:
        days = PaymentService.parse_credit_days(payment_terms)
        return base_date + timedelta(days=days)

    # =====================================================
    # Create a payment (scheduled or recorded) for an invoice
    # =====================================================

    @staticmethod
    def create_payment(db: Session, data: dict) -> Payment:
        invoice_id = data.get("invoice_id")
        invoice = db.query(Invoice).filter(
            Invoice.id == invoice_id
        ).first()
        if not invoice:
            raise ValueError("Invoice not found")

        payment_type = data.get("payment_type", "Full")
        if payment_type not in VALID_TYPES:
            raise ValueError(f"Invalid payment type: {payment_type}")

        po = None
        if invoice.po_id:
            po = db.query(PurchaseOrder).filter(
                PurchaseOrder.id == invoice.po_id
            ).first()

        # Due date: explicit if provided, else computed from PO payment terms
        # relative to the invoice date (or today when the invoice has none).
        due_date = data.get("due_date")
        if not due_date:
            base = invoice.invoice_date or date.today()
            terms = po.payment_terms if po else None
            due_date = PaymentService.compute_due_date(base, terms)

        payment = Payment(
            invoice_id=invoice_id,
            po_id=invoice.po_id,
            vendor_id=invoice.vendor_id,
            payment_type=payment_type,
            amount=data.get("amount", 0) or 0,
            due_date=due_date,
            paid_date=data.get("paid_date"),
            reference=data.get("reference"),
            status=data.get("status", "Pending"),
            remarks=data.get("remarks"),
            created_by=data["created_by"]
        )
        # Derive status from paid/due when not explicitly Paid.
        payment.status = PaymentService._derive_status(payment)

        db.add(payment)
        db.commit()
        db.refresh(payment)
        return payment

    # =====================================================
    # Record a payment as paid
    # =====================================================

    @staticmethod
    def mark_paid(
        db: Session,
        payment_id: int,
        paid_date: date = None,
        reference: str = None
    ) -> Payment:
        payment = db.query(Payment).filter(
            Payment.id == payment_id
        ).first()
        if not payment:
            raise ValueError("Payment not found")

        payment.paid_date = paid_date or date.today()
        if reference:
            payment.reference = reference
        payment.status = "Paid"

        # If every payment on the invoice is paid, mark the invoice Paid.
        invoice = db.query(Invoice).filter(
            Invoice.id == payment.invoice_id
        ).first()
        if invoice:
            others = db.query(Payment).filter(
                Payment.invoice_id == invoice.id
            ).all()
            if others and all(p.status == "Paid" for p in others):
                invoice.status = "Paid"

        db.commit()
        db.refresh(payment)
        return payment

    # =====================================================
    # Status derivation (Pending / Due / Overdue / Paid)
    # =====================================================

    @staticmethod
    def _derive_status(payment: Payment) -> str:
        if payment.paid_date is not None or payment.status == "Paid":
            return "Paid"
        if payment.status == "Partial":
            return "Partial"
        if payment.due_date is None:
            return "Pending"
        today = date.today()
        if payment.due_date < today:
            return "Overdue"
        if (payment.due_date - today).days <= DUE_SOON_WINDOW:
            return "Due"
        return "Pending"

    @staticmethod
    def refresh_statuses(db: Session) -> int:
        """
        Recomputes Pending/Due/Overdue for all unpaid payments based on the
        current date. Returns the number of rows whose status changed.
        """
        payments = db.query(Payment).filter(
            Payment.status != "Paid"
        ).all()
        changed = 0
        for p in payments:
            new_status = PaymentService._derive_status(p)
            if new_status != p.status:
                p.status = new_status
                changed += 1
        if changed:
            db.commit()
        return changed

    # =====================================================
    # Queries + outstanding dashboard aggregation
    # =====================================================

    @staticmethod
    def serialize(db: Session, payment: Payment) -> dict:
        vendor = db.query(Supplier).filter(
            Supplier.id == payment.vendor_id
        ).first()
        invoice = db.query(Invoice).filter(
            Invoice.id == payment.invoice_id
        ).first()
        po = None
        if payment.po_id:
            po = db.query(PurchaseOrder).filter(
                PurchaseOrder.id == payment.po_id
            ).first()
        return {
            "id": payment.id,
            "invoice_id": payment.invoice_id,
            "invoice_number": invoice.invoice_number if invoice else None,
            "po_id": payment.po_id,
            "po_number": po.po_number if po else None,
            "vendor_id": payment.vendor_id,
            "vendor_name": vendor.company_name if vendor else None,
            "payment_type": payment.payment_type,
            "amount": float(payment.amount or 0),
            "due_date": (
                payment.due_date.isoformat() if payment.due_date else None
            ),
            "paid_date": (
                payment.paid_date.isoformat() if payment.paid_date else None
            ),
            "reference": payment.reference,
            "status": payment.status,
            "remarks": payment.remarks
        }

    @staticmethod
    def list_payments(db: Session) -> list:
        payments = db.query(Payment).order_by(
            Payment.due_date.asc().nullslast()
        ).all()
        return [PaymentService.serialize(db, p) for p in payments]

    @staticmethod
    def outstanding_summary(db: Session) -> dict:
        """
        Aggregate of unpaid payments for the outstanding / overdue board.
        """
        PaymentService.refresh_statuses(db)
        payments = db.query(Payment).filter(
            Payment.status != "Paid"
        ).all()

        totals = {
            "outstanding_total": 0.0,
            "overdue_total": 0.0,
            "due_soon_total": 0.0,
            "overdue_count": 0,
            "due_soon_count": 0,
            "pending_count": 0
        }
        for p in payments:
            amt = float(p.amount or 0)
            totals["outstanding_total"] += amt
            if p.status == "Overdue":
                totals["overdue_total"] += amt
                totals["overdue_count"] += 1
            elif p.status == "Due":
                totals["due_soon_total"] += amt
                totals["due_soon_count"] += 1
            else:
                totals["pending_count"] += 1

        totals["outstanding_total"] = round(totals["outstanding_total"], 2)
        totals["overdue_total"] = round(totals["overdue_total"], 2)
        totals["due_soon_total"] = round(totals["due_soon_total"], 2)
        return totals
