from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.schemas.negotiation import NegotiationCreate, NegotiationResponse
from app.services.negotiation_service import NegotiationService

router = APIRouter(
    tags=["Negotiation"]
)


# =====================================================
# Record a negotiation round (optionally send WhatsApp)
# =====================================================

@router.post("/rfqs/{rfq_id}/negotiations")
def add_negotiation_round(
    rfq_id: int,
    payload: NegotiationCreate,
    db: Session = Depends(get_db)
):
    try:
        result = NegotiationService.add_round(
            db=db,
            rfq_id=rfq_id,
            vendor_id=payload.vendor_id,
            channel=payload.channel,
            created_by=payload.created_by,
            quotation_id=payload.quotation_id,
            original_price=payload.original_price,
            counter_price=payload.counter_price,
            agreed_price=payload.agreed_price,
            summary=payload.summary,
            outcome=payload.outcome,
            send_whatsapp=payload.send_whatsapp,
            whatsapp_message=payload.whatsapp_message
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "negotiation": NegotiationResponse.model_validate(
            result["negotiation"]
        ),
        "whatsapp_result": result["whatsapp_result"]
    }


# =====================================================
# Full negotiation timeline for an RFQ
# =====================================================

@router.get("/rfqs/{rfq_id}/negotiations")
def list_negotiation_rounds(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    return {
        "rfq_id": rfq_id,
        "rounds": NegotiationService.list_rounds(db, rfq_id)
    }


# =====================================================
# AI suggestions: price history + target range
# =====================================================

@router.get("/rfqs/{rfq_id}/negotiations/suggestions")
def negotiation_suggestions(
    rfq_id: int,
    db: Session = Depends(get_db)
):
    try:
        return NegotiationService.get_suggestions(db, rfq_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
