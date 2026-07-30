"""
ReminderService — automated WhatsApp reminders (Phase 7).

Three reminder categories, each idempotent via reminders_log.dedup_key:
1. RFQ no-reply nudges at 12 / 24 / 48 hours after the RFQ was sent
   to a vendor who has not yet quoted.
2. Payment due-tomorrow and overdue alerts (overdue repeats daily).
3. Quotation validity expiry alerts (2 days before expiry).

Payment reminders are internal: they go to ADMIN_WHATSAPP_NUMBER if
configured, otherwise they are recorded with status LOGGED so the
dashboard still shows them.
"""

import os
from datetime import datetime, timezone, date, timedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.reminder_log import ReminderLog
from app.models.rfq import RFQ
from app.models.rfq_vendor import RFQVendor
from app.models.quotation import Quotation
from app.models.payment import Payment
from app.models.invoice import Invoice
from app.models.supplier import Supplier

# Imported so SQLAlchemy can resolve all mapper relationships when this
# service is used standalone (same pattern as invoice_service).
from app.models.rfq_item import RFQItem  # noqa: F401
from app.models.quotation_item import QuotationItem  # noqa: F401
from app.models.rfq_award import RFQAward  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401
from app.models.purchase_order import PurchaseOrder  # noqa: F401
from app.models.purchase_order_item import PurchaseOrderItem  # noqa: F401
from app.models.delivery import Delivery  # noqa: F401
from app.models.delivery_item import DeliveryItem  # noqa: F401
from app.models.invoice_item import InvoiceItem  # noqa: F401

from app.services.whatsapp_service import send_text_message
from app.services.payment_service import PaymentService

RFQ_REMINDER_HOURS = [12, 24, 48]
QUOTATION_EXPIRY_WINDOW_DAYS = 2

# RFQ statuses still awaiting vendor replies
RFQ_OPEN_STATUSES = ["Sent", "Vendor Viewed"]


class ReminderService:

    # -------------------------------------------------
    # Internals
    # -------------------------------------------------

    @staticmethod
    def _already_sent(db: Session, dedup_key: str) -> bool:
        return db.query(ReminderLog).filter(
            ReminderLog.dedup_key == dedup_key
        ).first() is not None

    @staticmethod
    def _record(
        db: Session,
        reminder_type: str,
        entity_type: str,
        entity_id: int,
        dedup_key: str,
        message: str,
        recipient: str = None,
        vendor_id: int = None
    ):
        """Send (if recipient) and log exactly once. Returns the log row or None."""
        status = "LOGGED"
        error = None

        if recipient:
            try:
                send_text_message(phone_number=recipient, message=message)
                status = "SENT"
            except Exception as e:
                status = "FAILED"
                error = str(e)

        entry = ReminderLog(
            reminder_type=reminder_type,
            entity_type=entity_type,
            entity_id=entity_id,
            vendor_id=vendor_id,
            dedup_key=dedup_key,
            recipient=recipient,
            message=message,
            status=status,
            error=error
        )
        db.add(entry)
        try:
            db.commit()
        except IntegrityError:
            # Concurrent duplicate — another run already logged it.
            db.rollback()
            return None
        db.refresh(entry)
        return entry

    # -------------------------------------------------
    # 1. RFQ no-reply reminders (12 / 24 / 48 hrs)
    # -------------------------------------------------

    @staticmethod
    def run_rfq_no_reply_reminders(db: Session) -> int:
        sent = 0
        now = datetime.now(timezone.utc)

        rfqs = db.query(RFQ).filter(RFQ.status.in_(RFQ_OPEN_STATUSES)).all()

        for rfq in rfqs:
            for rv in rfq.vendors:
                if not rv.sent_at:
                    continue

                # Vendor already quoted → no reminder needed
                has_quote = db.query(Quotation).filter(
                    Quotation.rfq_id == rfq.id,
                    Quotation.vendor_id == rv.vendor_id
                ).first()
                if has_quote:
                    continue

                supplier = db.query(Supplier).filter(
                    Supplier.id == rv.vendor_id
                ).first()
                if not supplier or not supplier.whatsapp_number:
                    continue

                sent_at = rv.sent_at
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                elapsed_hours = (now - sent_at).total_seconds() / 3600

                for h in RFQ_REMINDER_HOURS:
                    if elapsed_hours < h:
                        continue
                    dedup_key = f"RFQ_NO_REPLY_{h}H:{rfq.id}:{rv.vendor_id}"
                    if ReminderService._already_sent(db, dedup_key):
                        continue

                    message = (
                        f"Gentle reminder from *Abhinav Group* 🙏\n\n"
                        f"We are awaiting your quotation for RFQ "
                        f"*{rfq.rfq_number}* ({rfq.project_name}).\n\n"
                        f"Kindly share your best rates at the earliest. "
                        f"You can simply send the quotation PDF or photo here."
                    )
                    entry = ReminderService._record(
                        db=db,
                        reminder_type=f"RFQ_NO_REPLY_{h}H",
                        entity_type="RFQ",
                        entity_id=rfq.id,
                        dedup_key=dedup_key,
                        message=message,
                        recipient=supplier.whatsapp_number,
                        vendor_id=supplier.id
                    )
                    if entry:
                        sent += 1
        return sent

    # -------------------------------------------------
    # 2. Payment due-tomorrow + overdue reminders
    # -------------------------------------------------

    @staticmethod
    def run_payment_reminders(db: Session) -> int:
        sent = 0
        today = date.today()
        tomorrow = today + timedelta(days=1)
        admin_number = os.getenv("ADMIN_WHATSAPP_NUMBER")

        PaymentService.refresh_statuses(db)

        payments = db.query(Payment).filter(
            Payment.status.notin_(["Paid"]),
            Payment.due_date.isnot(None),
            Payment.due_date <= tomorrow
        ).all()

        for p in payments:
            invoice = db.query(Invoice).filter(Invoice.id == p.invoice_id).first()
            vendor = db.query(Supplier).filter(Supplier.id == p.vendor_id).first()
            inv_no = invoice.invoice_number if invoice else f"#{p.invoice_id}"
            vendor_name = vendor.company_name if vendor else "vendor"

            if p.due_date == tomorrow:
                reminder_type = "PAYMENT_DUE_TOMORROW"
                dedup_key = f"PAYMENT_DUE_TOMORROW:{p.id}"
                message = (
                    f"⏰ Payment due tomorrow: ₹{float(p.amount):,.2f} "
                    f"to {vendor_name} against invoice {inv_no} "
                    f"(due {p.due_date.isoformat()})."
                )
            elif p.due_date < today:
                reminder_type = "PAYMENT_OVERDUE"
                # Repeats daily until paid — date in the key
                dedup_key = f"PAYMENT_OVERDUE:{p.id}:{today.isoformat()}"
                days_late = (today - p.due_date).days
                message = (
                    f"🔴 Payment OVERDUE by {days_late} day(s): "
                    f"₹{float(p.amount):,.2f} to {vendor_name} "
                    f"against invoice {inv_no} (was due {p.due_date.isoformat()})."
                )
            else:
                continue

            if ReminderService._already_sent(db, dedup_key):
                continue

            entry = ReminderService._record(
                db=db,
                reminder_type=reminder_type,
                entity_type="Payment",
                entity_id=p.id,
                dedup_key=dedup_key,
                message=message,
                recipient=admin_number,
                vendor_id=p.vendor_id
            )
            if entry:
                sent += 1
        return sent

    # -------------------------------------------------
    # 3. Quotation validity expiry alerts
    # -------------------------------------------------

    @staticmethod
    def run_quotation_expiry_alerts(db: Session) -> int:
        sent = 0
        today = date.today()
        window_end = today + timedelta(days=QUOTATION_EXPIRY_WINDOW_DAYS)

        quotes = db.query(Quotation).filter(
            Quotation.is_latest.is_(True),
            Quotation.validity_date.isnot(None),
            Quotation.validity_date >= today,
            Quotation.validity_date <= window_end
        ).all()

        for q in quotes:
            rfq = db.query(RFQ).filter(RFQ.id == q.rfq_id).first()
            if rfq and rfq.status in ["Closed", "Cancelled"]:
                continue

            dedup_key = f"QUOTATION_EXPIRY:{q.id}"
            if ReminderService._already_sent(db, dedup_key):
                continue

            supplier = db.query(Supplier).filter(Supplier.id == q.vendor_id).first()
            recipient = supplier.whatsapp_number if supplier else None

            message = (
                f"Hello from *Abhinav Group* 👋\n\n"
                f"Your quotation *{q.quotation_number}*"
                f"{' for RFQ ' + rfq.rfq_number if rfq else ''} "
                f"is valid only till *{q.validity_date.isoformat()}*.\n\n"
                f"Kindly confirm if the quoted rates can be extended, "
                f"or share a revised quotation."
            )
            entry = ReminderService._record(
                db=db,
                reminder_type="QUOTATION_EXPIRY",
                entity_type="Quotation",
                entity_id=q.id,
                dedup_key=dedup_key,
                message=message,
                recipient=recipient,
                vendor_id=q.vendor_id
            )
            if entry:
                sent += 1
        return sent

    # -------------------------------------------------
    # Orchestration
    # -------------------------------------------------

    @staticmethod
    def run_all(db: Session) -> dict:
        return {
            "rfq_no_reply": ReminderService.run_rfq_no_reply_reminders(db),
            "payments": ReminderService.run_payment_reminders(db),
            "quotation_expiry": ReminderService.run_quotation_expiry_alerts(db)
        }

    # -------------------------------------------------
    # Serialization / listing
    # -------------------------------------------------

    @staticmethod
    def serialize(entry: ReminderLog) -> dict:
        return {
            "id": entry.id,
            "reminder_type": entry.reminder_type,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "vendor_id": entry.vendor_id,
            "recipient": entry.recipient,
            "message": entry.message,
            "status": entry.status,
            "error": entry.error,
            "created_at": entry.created_at.isoformat() if entry.created_at else None
        }

    @staticmethod
    def list_entries(db: Session, limit: int = 200):
        entries = db.query(ReminderLog).order_by(
            ReminderLog.created_at.desc()
        ).limit(limit).all()
        return [ReminderService.serialize(e) for e in entries]
