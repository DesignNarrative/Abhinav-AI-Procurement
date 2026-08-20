"""
Quotation Comparison + Vendor Selection (Award) engine.

Responsibilities:
1. Build a side-by-side comparison matrix of all LATEST quotations for an RFQ
   (per-item landed rates, totals, terms, brand) with L1/L2/L3 ranking.
2. Weighted scoring engine with configurable weights (scoring_config table).
   The AI recommendation NEVER auto-selects — the Purchase Manager decides.
3. Record the final vendor selection (award) with a full audit trail.
"""

import re
from sqlalchemy.orm import Session

from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
# Imported so the RFQ mapper's relationships always resolve, even when this
# service is used standalone (scripts / background jobs).
from app.models.rfq_vendor import RFQVendor  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.supplier import Supplier
from app.models.rfq_award import RFQAward
from app.models.scoring_config import ScoringConfig


# Neutral score used when there is no historical data yet for a criteria
# (quality / vendor rating / risk are data-driven from Phase 8 onwards).
NEUTRAL_SCORE = 50.0

DEFAULT_WEIGHTS = {
    "price": 40.0,
    "quality": 20.0,
    "delivery": 15.0,
    "payment_terms": 10.0,
    "vendor_rating": 10.0,
    "risk": 5.0
}


class ComparisonService:

    # ──────────────────────────────────────────────────
    # Scoring weights (configurable)
    # ──────────────────────────────────────────────────

    @staticmethod
    def get_weights(db: Session) -> dict:
        """Return active scoring weights, seeding defaults on first use."""
        rows = db.query(ScoringConfig).filter(
            ScoringConfig.is_active == True  # noqa: E712
        ).all()

        if not rows:
            for name, weight in DEFAULT_WEIGHTS.items():
                db.add(ScoringConfig(criteria_name=name, weight=weight))
            db.commit()
            return dict(DEFAULT_WEIGHTS)

        return {r.criteria_name: float(r.weight) for r in rows}

    @staticmethod
    def update_weights(db: Session, weights: dict) -> dict:
        """Update scoring weights. Weights must be >= 0 and sum to 100."""
        total = sum(weights.values())
        if round(total, 2) != 100.0:
            raise ValueError(
                f"Scoring weights must sum to 100 (got {total})."
            )
        if any(w < 0 for w in weights.values()):
            raise ValueError("Scoring weights cannot be negative.")

        # Ensure defaults exist first
        ComparisonService.get_weights(db)

        for name, weight in weights.items():
            row = db.query(ScoringConfig).filter(
                ScoringConfig.criteria_name == name
            ).first()
            if row:
                row.weight = weight
            else:
                db.add(ScoringConfig(criteria_name=name, weight=weight))
        db.commit()
        return ComparisonService.get_weights(db)

    # ──────────────────────────────────────────────────
    # Criteria scores (0-100, higher is better)
    # ──────────────────────────────────────────────────

    @staticmethod
    def _extract_days(text: str) -> int:
        """Pull the first integer out of a free-text terms string."""
        if not text:
            return None
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _price_score(grand_total: float, lowest_total: float) -> float:
        if not grand_total or grand_total <= 0:
            return 0.0
        return round(min(100.0, (lowest_total / grand_total) * 100.0), 1)

    @staticmethod
    def _delivery_score(delivery_timeline: str, fastest_days: int) -> float:
        days = ComparisonService._extract_days(delivery_timeline)
        if days is None or fastest_days is None:
            return NEUTRAL_SCORE
        if days <= 0:
            return 100.0
        return round(min(100.0, (fastest_days / days) * 100.0), 1)

    @staticmethod
    def _payment_terms_score(payment_terms: str) -> float:
        """
        Heuristic favouring credit-friendly terms:
        advance payment is worst, immediate is middle,
        longer credit periods score higher.
        """
        if not payment_terms:
            return NEUTRAL_SCORE
        terms = payment_terms.lower()
        if "advance" in terms:
            return 25.0
        credit_days = ComparisonService._extract_days(terms)
        if credit_days and ("day" in terms or "credit" in terms):
            return round(min(100.0, 50.0 + credit_days), 1)
        if "immediate" in terms or "against delivery" in terms:
            return 50.0
        return NEUTRAL_SCORE

    # ──────────────────────────────────────────────────
    # Comparison matrix
    # ──────────────────────────────────────────────────

    @staticmethod
    def build_comparison(db: Session, rfq_id: int) -> dict:
        """
        Build the full comparison payload for an RFQ:
        - vendor columns (latest quotation of each vendor)
        - item rows with per-vendor landed rates + L1/L2/L3 rank
        - weighted scores + AI recommendation with reasons
        """
        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if not rfq:
            return None

        rfq_items = (
            db.query(RFQItem)
            .filter(RFQItem.rfq_id == rfq_id)
            .order_by(RFQItem.id.asc())
            .all()
        )

        quotations = (
            db.query(Quotation)
            .filter(
                Quotation.rfq_id == rfq_id,
                Quotation.is_latest == True  # noqa: E712
            )
            .order_by(Quotation.grand_total.asc())
            .all()
        )

        award = db.query(RFQAward).filter(
            RFQAward.rfq_id == rfq_id
        ).first()

        weights = ComparisonService.get_weights(db)

        # ── Vendor columns ────────────────────────────
        vendor_columns = []
        for q in quotations:
            vendor = db.query(Supplier).filter(
                Supplier.id == q.vendor_id
            ).first()
            vendor_columns.append({
                "quotation_id": q.id,
                "quotation_number": q.quotation_number,
                "revision_number": q.revision_number,
                "vendor_id": q.vendor_id,
                "vendor_name": vendor.company_name if vendor else "Unknown",
                "grand_total": float(q.grand_total or 0),
                "freight_amount_total": float(q.freight_amount_total or 0),
                "loading_unloading_total": float(q.loading_unloading_total or 0),
                "payment_terms": q.payment_terms,
                "delivery_timeline": q.delivery_timeline,
                "validity_date": str(q.validity_date) if q.validity_date else None,
                "date_received": str(q.date_received),
                "status": q.status,
                "creation_source": q.creation_source
            })

        # ── Item rows with per-vendor cells + rank ────
        item_rows = []
        for item in rfq_items:
            cells = []
            for q in quotations:
                qi = (
                    db.query(QuotationItem)
                    .filter(
                        QuotationItem.quotation_id == q.id,
                        QuotationItem.rfq_item_id == item.id
                    )
                    .first()
                )
                if qi and qi.is_quoted:
                    cells.append({
                        "quotation_id": q.id,
                        "is_quoted": True,
                        "basic_rate": float(qi.basic_rate or 0),
                        "discount_percent": float(qi.discount_percent or 0),
                        "tax_percent": float(qi.tax_percent or 0),
                        "freight_amount": float(qi.freight_amount or 0),
                        "final_landed_rate": float(qi.final_landed_rate or 0),
                        "total_item_amount": float(qi.total_item_amount or 0),
                        "brand_offered": qi.brand_offered,
                        "quoted_quantity": float(qi.quoted_quantity or 0),
                        "remarks": qi.remarks,
                        "rank": None
                    })
                else:
                    cells.append({
                        "quotation_id": q.id,
                        "is_quoted": False,
                        "rank": None
                    })

            # Rank quoted cells by landed rate: L1 = lowest
            quoted = sorted(
                [c for c in cells if c["is_quoted"] and c["final_landed_rate"] > 0],
                key=lambda c: c["final_landed_rate"]
            )
            for pos, cell in enumerate(quoted, start=1):
                cell["rank"] = f"L{pos}"

            item_rows.append({
                "rfq_item_id": item.id,
                "material_name": item.material_name,
                "material_category": item.material_category,
                "quantity": float(item.quantity),
                "unit": item.unit,
                "brand_required": item.brand_required,
                "cells": cells
            })

        # ── Weighted scoring ──────────────────────────
        totals = [v["grand_total"] for v in vendor_columns if v["grand_total"] > 0]
        lowest_total = min(totals) if totals else 0.0
        highest_total = max(totals) if totals else 0.0

        delivery_days = [
            d for d in (
                ComparisonService._extract_days(v["delivery_timeline"])
                for v in vendor_columns
            )
            if d is not None
        ]
        fastest_days = min(delivery_days) if delivery_days else None

        # Compute cost savings and pros/cons for each vendor
        for v in vendor_columns:
            v["cost_savings"] = float(highest_total - v["grand_total"])
            pros = []
            cons = []

            # Price checks
            if lowest_total > 0:
                if v["grand_total"] == lowest_total:
                    pros.append("Lowest price (L1)")
                elif v["grand_total"] <= lowest_total * 1.05:
                    pros.append("Competitive price (within 5% of L1)")
                elif highest_total > lowest_total and v["grand_total"] == highest_total:
                    cons.append("Highest quote among vendors")

            # Delivery checks
            days = ComparisonService._extract_days(v["delivery_timeline"])
            if days is not None and fastest_days is not None:
                if days == fastest_days:
                    pros.append("Fastest delivery timeline")
                elif days > fastest_days + 7:
                    cons.append("Slower delivery timeline")

            # Payment terms checks
            pt = (v["payment_terms"] or "").lower()
            if "credit" in pt or "days" in pt:
                pros.append("Offers credit payment terms")
            elif "advance" in pt or "immediate" in pt:
                cons.append("Requires upfront or immediate payment")

            v["pros"] = pros
            v["cons"] = cons

        scores = []
        for v in vendor_columns:
            criteria = {
                "price": ComparisonService._price_score(
                    v["grand_total"], lowest_total
                ),
                "quality": NEUTRAL_SCORE,
                "delivery": ComparisonService._delivery_score(
                    v["delivery_timeline"], fastest_days
                ),
                "payment_terms": ComparisonService._payment_terms_score(
                    v["payment_terms"]
                ),
                "vendor_rating": NEUTRAL_SCORE,
                "risk": NEUTRAL_SCORE
            }
            total_score = round(
                sum(
                    criteria[name] * (weights.get(name, 0.0) / 100.0)
                    for name in criteria
                ),
                1
            )
            scores.append({
                "quotation_id": v["quotation_id"],
                "vendor_id": v["vendor_id"],
                "vendor_name": v["vendor_name"],
                "criteria_scores": criteria,
                "total_score": total_score
            })

        # ── AI recommendation (advisory only) ─────────
        recommendation = None
        if scores:
            best = max(scores, key=lambda s: s["total_score"])
            best_vendor = next(
                v for v in vendor_columns
                if v["quotation_id"] == best["quotation_id"]
            )
            reasons = []
            if best_vendor["grand_total"] == lowest_total:
                reasons.append("Lowest overall landed cost")
            else:
                extra = best_vendor["grand_total"] - lowest_total
                reasons.append(
                    f"Not the lowest price (₹{extra:,.2f} above L1) but "
                    f"scores best on the weighted criteria"
                )
            if best["criteria_scores"]["delivery"] >= 99.9:
                reasons.append("Fastest delivery timeline offered")
            if best["criteria_scores"]["payment_terms"] > NEUTRAL_SCORE:
                reasons.append(
                    f"Favourable payment terms: {best_vendor['payment_terms']}"
                )
            reasons.append(
                "Quality / rating / risk are neutral until vendor "
                "performance history builds up"
            )
            recommendation = {
                "quotation_id": best["quotation_id"],
                "vendor_id": best["vendor_id"],
                "vendor_name": best["vendor_name"],
                "total_score": best["total_score"],
                "reasons": reasons,
                "note": (
                    "This is an advisory recommendation. "
                    "Final selection is always made by the Purchase Manager."
                )
            }

        return {
            "rfq_id": rfq.id,
            "rfq_number": rfq.rfq_number,
            "rfq_status": rfq.status,
            "project_name": rfq.project_name,
            "site_name": rfq.site_name,
            "quotation_count": len(vendor_columns),
            "weights": weights,
            "vendors": vendor_columns,
            "items": item_rows,
            "scores": scores,
            "recommendation": recommendation,
            "award": {
                "id": award.id,
                "quotation_id": award.quotation_id,
                "vendor_id": award.vendor_id,
                "selection_reason": award.selection_reason,
                "remarks": award.remarks,
                "approved_by": award.approved_by,
                "awarded_at": str(award.awarded_at)
            } if award else None
        }

    # ──────────────────────────────────────────────────
    # Award (final vendor selection)
    # ──────────────────────────────────────────────────

    @staticmethod
    def create_award(
        db: Session,
        rfq_id: int,
        quotation_id: int,
        selection_reason: str,
        approved_by: str,
        remarks: str = None
    ) -> RFQAward:
        """
        Record the final vendor selection for an RFQ.
        Raises ValueError on any business rule violation —
        nothing is persisted in that case.
        """
        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if not rfq:
            raise ValueError("RFQ not found.")

        existing = db.query(RFQAward).filter(
            RFQAward.rfq_id == rfq_id
        ).first()
        if existing:
            raise ValueError(
                f"RFQ {rfq.rfq_number} is already awarded "
                f"(award id {existing.id})."
            )

        quotation = db.query(Quotation).filter(
            Quotation.id == quotation_id,
            Quotation.rfq_id == rfq_id
        ).first()
        if not quotation:
            raise ValueError(
                "Quotation not found or does not belong to this RFQ."
            )
        if not quotation.is_latest:
            raise ValueError(
                "Only the latest revision of a quotation can be awarded."
            )

        award = RFQAward(
            rfq_id=rfq_id,
            quotation_id=quotation.id,
            vendor_id=quotation.vendor_id,
            selection_reason=selection_reason.strip(),
            remarks=remarks.strip() if remarks else None,
            approved_by=approved_by.strip()
        )
        db.add(award)

        # Mark the winning quotation and move the RFQ forward
        quotation.status = "Selected"
        rfq.status = "Awarded"

        db.commit()
        db.refresh(award)
        return award

    @staticmethod
    def get_award(db: Session, rfq_id: int) -> RFQAward:
        return db.query(RFQAward).filter(
            RFQAward.rfq_id == rfq_id
        ).first()
