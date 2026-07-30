from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.schemas.payment import PaymentCreate, PaymentMarkPaid
from app.services.payment_service import PaymentService

router = APIRouter(tags=["Payments"])

templates = Jinja2Templates(directory="app/templates")


# =====================================================
# JSON API
# =====================================================

@router.post("/payments")
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)):
    try:
        payment = PaymentService.create_payment(db, payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PaymentService.serialize(db, payment)


@router.get("/payments")
def list_payments(db: Session = Depends(get_db)):
    PaymentService.refresh_statuses(db)
    return {"payments": PaymentService.list_payments(db)}


@router.post("/payments/{payment_id}/mark-paid")
def mark_paid(
    payment_id: int,
    payload: PaymentMarkPaid,
    db: Session = Depends(get_db)
):
    try:
        payment = PaymentService.mark_paid(
            db, payment_id, payload.paid_date, payload.reference
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PaymentService.serialize(db, payment)


@router.get("/payments/outstanding")
def outstanding(db: Session = Depends(get_db)):
    return PaymentService.outstanding_summary(db)


# =====================================================
# HTML Dashboard
# =====================================================

@router.get("/dashboard/payments", response_class=HTMLResponse)
def payments_page(request: Request, db: Session = Depends(get_db)):
    summary = PaymentService.outstanding_summary(db)
    payments = PaymentService.list_payments(db)
    return templates.TemplateResponse(
        request=request,
        name="payments_dashboard.html",
        context={
            "request": request,
            "summary": summary,
            "payments": payments
        }
    )
