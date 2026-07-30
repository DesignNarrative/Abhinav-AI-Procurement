from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.negotiation import Negotiation
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.supplier import Supplier

# Imported so SQLAlchemy can resolve every mapper when this
# service is used standalone (RFQ references these relationships).
from app.models.requirement import Requirement  # noqa: F401


class NegotiationService:
    """
    Negotiation round tracking per RFQ + vendor.

    Rounds are append-only: they are recorded, never edited or deleted,
    so the full negotiation history stays auditable forever.
    """

    # =====================================================
    # Add a negotiation round
    # =====================================================

    @staticmethod
    def add_round(
        db: Session,
        rfq_id: int,
        vendor_id: int,
        channel: str,
        created_by: str,
        quotation_id: int = None,
        original_price: float = None,
        counter_price: float = None,
        agreed_price: float = None,
        summary: str = None,
        outcome: str = "Pending",
        send_whatsapp: bool = False,
        whatsapp_message: str = None
    ) -> dict:

        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if not rfq:
            raise ValueError("RFQ not found")

        vendor = db.query(Supplier).filter(Supplier.id == vendor_id).first()
        if not vendor:
            raise ValueError("Vendor not found")

        assigned = db.query(RFQVendor).filter(
            RFQVendor.rfq_id == rfq_id,
            RFQVendor.vendor_id == vendor_id
        ).first()
        if not assigned:
            raise ValueError("Vendor is not assigned to this RFQ")

        if quotation_id:
            quotation = db.query(Quotation).filter(
                Quotation.id == quotation_id,
                Quotation.rfq_id == rfq_id,
                Quotation.vendor_id == vendor_id
            ).first()
            if not quotation:
                raise ValueError(
                    "Quotation does not belong to this RFQ and vendor"
                )

        # Sequential round number per RFQ + vendor
        last_round = db.query(
            func.max(Negotiation.round_number)
        ).filter(
            Negotiation.rfq_id == rfq_id,
            Negotiation.vendor_id == vendor_id
        ).scalar() or 0

        negotiation = Negotiation(
            rfq_id=rfq_id,
            vendor_id=vendor_id,
            quotation_id=quotation_id,
            round_number=last_round + 1,
            channel=channel,
            original_price=original_price,
            counter_price=counter_price,
            agreed_price=agreed_price,
            summary=summary,
            outcome=outcome,
            created_by=created_by
        )
        db.add(negotiation)

        # Move RFQ into Negotiation status (never override a final state)
        if rfq.status not in ("Awarded", "Closed", "Cancelled"):
            rfq.status = "Negotiation"

        whatsapp_result = None
        if send_whatsapp and whatsapp_message:
            from app.services.whatsapp_service import send_text_message

            phone = vendor.whatsapp_number
            if not phone.startswith("+"):
                phone = f"91{phone}" if len(phone) == 10 else phone

            whatsapp_result = send_text_message(phone, whatsapp_message)

        db.commit()
        db.refresh(negotiation)

        return {
            "negotiation": negotiation,
            "whatsapp_result": whatsapp_result
        }

    # =====================================================
    # Full negotiation timeline for an RFQ
    # =====================================================

    @staticmethod
    def list_rounds(db: Session, rfq_id: int) -> list:

        rounds = db.query(Negotiation).filter(
            Negotiation.rfq_id == rfq_id
        ).order_by(
            Negotiation.created_at.asc(),
            Negotiation.id.asc()
        ).all()

        result = []
        for n in rounds:
            result.append({
                "id": n.id,
                "rfq_id": n.rfq_id,
                "vendor_id": n.vendor_id,
                "vendor_name": n.vendor.company_name if n.vendor else None,
                "quotation_id": n.quotation_id,
                "quotation_number": (
                    n.quotation.quotation_number if n.quotation else None
                ),
                "round_number": n.round_number,
                "channel": n.channel,
                "original_price": (
                    float(n.original_price)
                    if n.original_price is not None else None
                ),
                "counter_price": (
                    float(n.counter_price)
                    if n.counter_price is not None else None
                ),
                "agreed_price": (
                    float(n.agreed_price)
                    if n.agreed_price is not None else None
                ),
                "summary": n.summary,
                "outcome": n.outcome,
                "created_by": n.created_by,
                "created_at": n.created_at.isoformat()
            })
        return result

    # =====================================================
    # AI suggestion panel: price history + target range
    # =====================================================

    @staticmethod
    def get_suggestions(db: Session, rfq_id: int) -> dict:
        """
        For each material in the RFQ: the best (L1) rate quoted in this
        RFQ, historical rates for the same material name from past
        quotations, and a computed target range for negotiation.
        Purely advisory — the purchase manager decides.
        """
        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if not rfq:
            raise ValueError("RFQ not found")

        suggestions = []

        for item in rfq.items:
            # Best rate quoted for this item in the current RFQ
            current = db.query(
                QuotationItem, Quotation
            ).join(
                Quotation, QuotationItem.quotation_id == Quotation.id
            ).filter(
                QuotationItem.rfq_item_id == item.id,
                QuotationItem.is_quoted.is_(True),
                Quotation.is_latest.is_(True)
            ).all()

            l1_rate = None
            l1_vendor = None
            for qi, q in current:
                rate = float(qi.final_landed_rate or 0)
                if rate > 0 and (l1_rate is None or rate < l1_rate):
                    l1_rate = rate
                    l1_vendor = (
                        q.vendor.company_name if q.vendor else None
                    )

            # Historical rates: same material name in OTHER RFQs
            history = db.query(
                QuotationItem.final_landed_rate,
                Quotation.date_received
            ).join(
                Quotation, QuotationItem.quotation_id == Quotation.id
            ).join(
                RFQItem, QuotationItem.rfq_item_id == RFQItem.id
            ).filter(
                func.lower(RFQItem.material_name) ==
                item.material_name.lower(),
                RFQItem.rfq_id != rfq_id,
                QuotationItem.is_quoted.is_(True),
                Quotation.is_latest.is_(True),
                QuotationItem.final_landed_rate > 0
            ).order_by(
                Quotation.date_received.desc()
            ).all()

            hist_rates = [float(r) for r, _ in history]
            hist_min = min(hist_rates) if hist_rates else None
            hist_avg = (
                round(sum(hist_rates) / len(hist_rates), 2)
                if hist_rates else None
            )
            last_rate = hist_rates[0] if hist_rates else None
            last_date = (
                history[0][1].isoformat()
                if history and history[0][1] else None
            )

            # Target range: aim between best-ever rate and current L1
            target_low = None
            target_high = None
            if l1_rate is not None:
                target_high = round(l1_rate, 2)
                if hist_min is not None and hist_min < l1_rate:
                    target_low = round(hist_min, 2)
                else:
                    # No cheaper history — ask for a modest 3-5% cut
                    target_low = round(l1_rate * 0.95, 2)

            suggestions.append({
                "rfq_item_id": item.id,
                "material_name": item.material_name,
                "quantity": float(item.quantity),
                "unit": item.unit,
                "l1_rate": l1_rate,
                "l1_vendor": l1_vendor,
                "last_purchase_rate": last_rate,
                "last_purchase_date": last_date,
                "historical_min_rate": hist_min,
                "historical_avg_rate": hist_avg,
                "history_count": len(hist_rates),
                "target_low": target_low,
                "target_high": target_high
            })

        return {
            "rfq_id": rfq_id,
            "rfq_number": rfq.rfq_number,
            "items": suggestions,
            "note": (
                "Targets are advisory, computed from this RFQ's L1 rates "
                "and past quotation history for the same material."
            )
        }
