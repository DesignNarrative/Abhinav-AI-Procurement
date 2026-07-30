from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.schemas.comparison import (
    ScoringWeightsUpdate, AwardCreate, AwardResponse
)
from app.services.comparison_service import ComparisonService

router = APIRouter(
    tags=["Quotation Comparison & Award"]
)


# ──────────────────────────────────────────────────
# Comparison Matrix
# ──────────────────────────────────────────────────

@router.get("/rfqs/{rfq_id}/comparison")
def get_comparison(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    """
    Side-by-side comparison of all latest quotations for an RFQ:
    per-item landed rates with L1/L2/L3 ranking, weighted scores
    and an advisory AI recommendation.
    """
    result = ComparisonService.build_comparison(db, rfq_id)
    if result is None:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return result


# ──────────────────────────────────────────────────
# Award (final vendor selection)
# ──────────────────────────────────────────────────

@router.post(
    "/rfqs/{rfq_id}/award",
    response_model=AwardResponse
)
def create_award(
    rfq_id: int,
    payload: AwardCreate,
    db: Session = Depends(get_db)
):
    """
    Record the final vendor selection for an RFQ.
    Marks the winning quotation as 'Selected' and the RFQ as 'Awarded'.
    """
    try:
        return ComparisonService.create_award(
            db=db,
            rfq_id=rfq_id,
            quotation_id=payload.quotation_id,
            selection_reason=payload.selection_reason,
            approved_by=payload.approved_by,
            remarks=payload.remarks
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/rfqs/{rfq_id}/award",
    response_model=AwardResponse
)
def get_award(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    award = ComparisonService.get_award(db, rfq_id)
    if not award:
        raise HTTPException(
            status_code=404,
            detail="No award recorded for this RFQ."
        )
    return award


# ──────────────────────────────────────────────────
# Scoring Config
# ──────────────────────────────────────────────────

@router.get("/scoring-config")
def get_scoring_weights(
    db: Session = Depends(get_db)
):
    return {"weights": ComparisonService.get_weights(db)}


@router.put("/scoring-config")
def update_scoring_weights(
    payload: ScoringWeightsUpdate,
    db: Session = Depends(get_db)
):
    try:
        weights = ComparisonService.update_weights(db, payload.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"weights": weights}
