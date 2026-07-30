"""
AnalyticsService — Phase 8 intelligence & reporting.

All read-only, computed from existing history:
  * Vendor scorecards (delivery success, quality, response rate, awards, spend)
  * Price intelligence (last / min / max / avg purchase price per material + trend)
  * Spend and savings reports (by project, category, vendor; negotiation savings;
    RFQ turnaround times)

Nothing here mutates data or auto-decides — it only surfaces numbers so the
purchase manager can act.
"""

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.supplier import Supplier
from app.models.rfq import RFQ
from app.models.rfq_vendor import RFQVendor
from app.models.rfq_item import RFQItem
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.rfq_award import RFQAward
from app.models.negotiation import Negotiation
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.delivery import Delivery
from app.models.delivery_item import DeliveryItem

# Resolve remaining mapper relationships when used standalone.
from app.models.invoice import Invoice  # noqa: F401
from app.models.invoice_item import InvoiceItem  # noqa: F401
from app.models.payment import Payment  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401

# Deliveries considered "successfully received"
DELIVERY_SUCCESS_STATUSES = ["Delivered", "Partially Delivered"]

# A live quote this much above the historical average is flagged
PRICE_ALERT_THRESHOLD = 1.10


def _f(value) -> float:
    return float(value) if value is not None else 0.0


class AnalyticsService:

    # =================================================
    # Vendor scorecard
    # =================================================

    @staticmethod
    def vendor_scorecard(db: Session, vendor_id: int) -> dict:
        vendor = db.query(Supplier).filter(Supplier.id == vendor_id).first()
        if not vendor:
            raise ValueError(f"Vendor {vendor_id} not found.")

        # --- response rate ---
        rfqs_invited = db.query(func.count(func.distinct(RFQVendor.rfq_id))).filter(
            RFQVendor.vendor_id == vendor_id
        ).scalar() or 0

        rfqs_quoted = db.query(func.count(func.distinct(Quotation.rfq_id))).filter(
            Quotation.vendor_id == vendor_id
        ).scalar() or 0

        response_rate = (rfqs_quoted / rfqs_invited * 100) if rfqs_invited else 0.0

        # --- awards won ---
        awards_won = db.query(func.count(RFQAward.id)).filter(
            RFQAward.vendor_id == vendor_id
        ).scalar() or 0

        award_rate = (awards_won / rfqs_quoted * 100) if rfqs_quoted else 0.0

        # --- deliveries (via this vendor's POs) ---
        po_ids = [
            row[0] for row in db.query(PurchaseOrder.id).filter(
                PurchaseOrder.vendor_id == vendor_id
            ).all()
        ]

        deliveries_total = 0
        deliveries_ok = 0
        quality_issues = 0
        if po_ids:
            deliveries_total = db.query(func.count(Delivery.id)).filter(
                Delivery.po_id.in_(po_ids)
            ).scalar() or 0

            deliveries_ok = db.query(func.count(Delivery.id)).filter(
                Delivery.po_id.in_(po_ids),
                Delivery.status.in_(DELIVERY_SUCCESS_STATUSES)
            ).scalar() or 0

            quality_issues = db.query(func.count(DeliveryItem.id)).join(
                Delivery, DeliveryItem.delivery_id == Delivery.id
            ).filter(
                Delivery.po_id.in_(po_ids),
                DeliveryItem.quality_ok.is_(False)
            ).scalar() or 0

        delivery_success_rate = (
            deliveries_ok / deliveries_total * 100
        ) if deliveries_total else 0.0

        # --- total spend ---
        total_spend = db.query(func.coalesce(func.sum(PurchaseOrder.grand_total), 0)).filter(
            PurchaseOrder.vendor_id == vendor_id
        ).scalar() or 0

        pos_count = len(po_ids)

        # --- composite score (0-100) ---
        # Weighted: response 25, delivery 35, quality 25, award 15.
        quality_score = 100.0
        if deliveries_total:
            # Penalise each quality issue, floored at 0
            quality_score = max(0.0, 100.0 - (quality_issues / deliveries_total * 100))

        composite = (
            response_rate * 0.25 +
            delivery_success_rate * 0.35 +
            quality_score * 0.25 +
            min(award_rate, 100.0) * 0.15
        )

        return {
            "vendor_id": vendor.id,
            "vendor_name": vendor.company_name,
            "supplier_code": vendor.supplier_code,
            "rfqs_invited": rfqs_invited,
            "rfqs_quoted": rfqs_quoted,
            "response_rate": round(response_rate, 1),
            "awards_won": awards_won,
            "award_rate": round(award_rate, 1),
            "purchase_orders": pos_count,
            "deliveries_total": deliveries_total,
            "deliveries_ok": deliveries_ok,
            "delivery_success_rate": round(delivery_success_rate, 1),
            "quality_issues": quality_issues,
            "quality_score": round(quality_score, 1),
            "total_spend": _f(total_spend),
            "score": round(composite, 1)
        }

    @staticmethod
    def all_vendor_scorecards(db: Session) -> list:
        vendors = db.query(Supplier).filter(
            Supplier.registration_status == "APPROVED"
        ).all()
        cards = [
            AnalyticsService.vendor_scorecard(db, v.id) for v in vendors
        ]
        # Best score first
        cards.sort(key=lambda c: c["score"], reverse=True)
        return cards

    # =================================================
    # Price intelligence
    # =================================================

    @staticmethod
    def price_history(db: Session, material_name: str) -> dict:
        """
        Purchase price history for a material, taken from PO line items
        (actual purchases). Returns min/max/avg/last + a simple trend.
        """
        rows = db.query(
            PurchaseOrderItem.final_landed_rate,
            PurchaseOrder.po_date,
            PurchaseOrder.po_number,
            Supplier.company_name
        ).join(
            PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id
        ).join(
            Supplier, PurchaseOrder.vendor_id == Supplier.id
        ).filter(
            func.lower(PurchaseOrderItem.material_name) == material_name.lower(),
            PurchaseOrderItem.final_landed_rate > 0
        ).order_by(PurchaseOrder.po_date.asc().nullsfirst()).all()

        history = [
            {
                "rate": _f(r[0]),
                "po_date": r[1].isoformat() if r[1] else None,
                "po_number": r[2],
                "vendor_name": r[3]
            }
            for r in rows
        ]

        rates = [h["rate"] for h in history]
        if not rates:
            return {
                "material_name": material_name,
                "count": 0,
                "last_price": None,
                "min_price": None,
                "max_price": None,
                "avg_price": None,
                "trend": "no_data",
                "history": []
            }

        avg_price = sum(rates) / len(rates)
        last_price = rates[-1]

        # Trend: compare last price to the average of everything before it
        trend = "stable"
        if len(rates) >= 2:
            prev_avg = sum(rates[:-1]) / len(rates[:-1])
            if last_price > prev_avg * 1.02:
                trend = "rising"
            elif last_price < prev_avg * 0.98:
                trend = "falling"

        return {
            "material_name": material_name,
            "count": len(rates),
            "last_price": round(last_price, 2),
            "min_price": round(min(rates), 2),
            "max_price": round(max(rates), 2),
            "avg_price": round(avg_price, 2),
            "trend": trend,
            "history": history
        }

    @staticmethod
    def evaluate_quote_price(db: Session, material_name: str, quoted_rate: float) -> dict:
        """Compare a live quoted rate against historical purchase price."""
        hist = AnalyticsService.price_history(db, material_name)
        result = {
            "material_name": material_name,
            "quoted_rate": round(float(quoted_rate), 2),
            "avg_price": hist["avg_price"],
            "last_price": hist["last_price"],
            "flag": False,
            "message": ""
        }
        if hist["count"] == 0:
            result["message"] = "No purchase history for this material yet."
            return result

        if quoted_rate > hist["avg_price"] * PRICE_ALERT_THRESHOLD:
            pct = (quoted_rate / hist["avg_price"] - 1) * 100
            result["flag"] = True
            result["message"] = (
                f"Quote is {pct:.0f}% above the historical average "
                f"(₹{hist['avg_price']:,.2f})."
            )
        else:
            result["message"] = "Quote is within the normal historical range."
        return result

    @staticmethod
    def price_intelligence_overview(db: Session, limit: int = 100) -> list:
        """Aggregate purchase price per material across all POs."""
        rows = db.query(
            PurchaseOrderItem.material_name,
            func.count(PurchaseOrderItem.id),
            func.min(PurchaseOrderItem.final_landed_rate),
            func.max(PurchaseOrderItem.final_landed_rate),
            func.avg(PurchaseOrderItem.final_landed_rate)
        ).filter(
            PurchaseOrderItem.final_landed_rate > 0
        ).group_by(
            PurchaseOrderItem.material_name
        ).order_by(
            func.count(PurchaseOrderItem.id).desc()
        ).limit(limit).all()

        return [
            {
                "material_name": r[0],
                "purchase_count": r[1],
                "min_price": round(_f(r[2]), 2),
                "max_price": round(_f(r[3]), 2),
                "avg_price": round(_f(r[4]), 2)
            }
            for r in rows
        ]

    # =================================================
    # Spend & savings reports
    # =================================================

    @staticmethod
    def spend_by_project(db: Session) -> list:
        rows = db.query(
            func.coalesce(RFQ.project_name, "Unlinked"),
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(PurchaseOrder.grand_total), 0)
        ).outerjoin(
            RFQ, PurchaseOrder.rfq_id == RFQ.id
        ).group_by(RFQ.project_name).order_by(
            func.sum(PurchaseOrder.grand_total).desc().nullslast()
        ).all()
        return [
            {"project_name": r[0], "po_count": r[1], "total_spend": _f(r[2])}
            for r in rows
        ]

    @staticmethod
    def spend_by_vendor(db: Session) -> list:
        rows = db.query(
            Supplier.company_name,
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(PurchaseOrder.grand_total), 0)
        ).join(
            Supplier, PurchaseOrder.vendor_id == Supplier.id
        ).group_by(Supplier.company_name).order_by(
            func.sum(PurchaseOrder.grand_total).desc().nullslast()
        ).all()
        return [
            {"vendor_name": r[0], "po_count": r[1], "total_spend": _f(r[2])}
            for r in rows
        ]

    @staticmethod
    def spend_by_category(db: Session) -> list:
        rows = db.query(
            func.coalesce(PurchaseOrderItem.material_category, "Uncategorised"),
            func.count(PurchaseOrderItem.id),
            func.coalesce(func.sum(PurchaseOrderItem.total_amount), 0)
        ).group_by(PurchaseOrderItem.material_category).order_by(
            func.sum(PurchaseOrderItem.total_amount).desc().nullslast()
        ).all()
        return [
            {"category": r[0], "item_count": r[1], "total_spend": _f(r[2])}
            for r in rows
        ]

    @staticmethod
    def negotiation_savings(db: Session) -> dict:
        """Savings = original_price - agreed_price across agreed negotiation rounds."""
        rounds = db.query(Negotiation).filter(
            Negotiation.agreed_price.isnot(None),
            Negotiation.original_price.isnot(None)
        ).all()

        total_saving = 0.0
        detail = []
        for n in rounds:
            saving = _f(n.original_price) - _f(n.agreed_price)
            if saving <= 0:
                continue
            total_saving += saving
            detail.append({
                "negotiation_id": n.id,
                "rfq_id": n.rfq_id,
                "vendor_id": n.vendor_id,
                "round_number": n.round_number,
                "original_price": _f(n.original_price),
                "agreed_price": _f(n.agreed_price),
                "saving": round(saving, 2)
            })
        return {
            "total_saving": round(total_saving, 2),
            "rounds_with_saving": len(detail),
            "detail": detail
        }

    @staticmethod
    def rfq_turnaround(db: Session) -> dict:
        """Average days between RFQ creation and award."""
        rows = db.query(
            RFQ.id, RFQ.rfq_number, RFQ.created_at, RFQAward.awarded_at
        ).join(
            RFQAward, RFQAward.rfq_id == RFQ.id
        ).all()

        durations = []
        detail = []
        for rfq_id, rfq_number, created_at, awarded_at in rows:
            if not created_at or not awarded_at:
                continue
            days = (awarded_at - created_at).total_seconds() / 86400
            durations.append(days)
            detail.append({
                "rfq_id": rfq_id,
                "rfq_number": rfq_number,
                "days": round(days, 1)
            })

        avg_days = round(sum(durations) / len(durations), 1) if durations else 0.0
        return {
            "awarded_rfqs": len(durations),
            "avg_turnaround_days": avg_days,
            "detail": detail
        }

    @staticmethod
    def reports_summary(db: Session) -> dict:
        return {
            "spend_by_project": AnalyticsService.spend_by_project(db),
            "spend_by_vendor": AnalyticsService.spend_by_vendor(db),
            "spend_by_category": AnalyticsService.spend_by_category(db),
            "negotiation_savings": AnalyticsService.negotiation_savings(db),
            "rfq_turnaround": AnalyticsService.rfq_turnaround(db)
        }
