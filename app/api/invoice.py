from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.invoice import Invoice
from app.models.invoice_item import InvoiceItem
from app.models.supplier import Supplier
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.schemas.invoice import InvoiceCreate, InvoiceStatusUpdate
from app.services.invoice_service import InvoiceService
from app.services.payment_service import PaymentService

router = APIRouter(tags=["Invoices"])

templates = Jinja2Templates(directory="app/templates")


# =====================================================
# JSON API
# =====================================================

@router.post("/invoices")
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db)):
    try:
        invoice = InvoiceService.create_invoice(db, payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return InvoiceService.serialize(db, invoice)


@router.get("/invoices")
def list_invoices(db: Session = Depends(get_db)):
    return {
        "invoices": [
            InvoiceService.serialize(db, inv)
            for inv in InvoiceService.list_invoices(db)
        ]
    }


@router.post("/invoices/{invoice_id}/match")
def run_match(invoice_id: int, db: Session = Depends(get_db)):
    try:
        result = InvoiceService.run_three_way_match(db, invoice_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.put("/invoices/{invoice_id}/status")
def update_invoice_status(
    invoice_id: int,
    payload: InvoiceStatusUpdate,
    db: Session = Depends(get_db)
):
    try:
        invoice = InvoiceService.update_status(
            db, invoice_id, payload.status, payload.approved_by
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return InvoiceService.serialize(db, invoice)


# =====================================================
# HTML Dashboard
# =====================================================

@router.get("/dashboard/invoices", response_class=HTMLResponse)
def invoice_list_page(request: Request, db: Session = Depends(get_db)):
    invoices = [
        InvoiceService.serialize(db, inv)
        for inv in InvoiceService.list_invoices(db)
    ]
    vendors = db.query(Supplier).filter(
        Supplier.registration_status == "APPROVED"
    ).order_by(Supplier.company_name.asc()).all()
    pos = db.query(PurchaseOrder).order_by(
        PurchaseOrder.created_at.desc()
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="invoice_management.html",
        context={
            "request": request,
            "invoices": invoices,
            "vendors": vendors,
            "pos": pos
        }
    )


@router.get("/dashboard/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_details_page(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    invoice = InvoiceService.get_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    items = db.query(InvoiceItem).filter(
        InvoiceItem.invoice_id == invoice_id
    ).order_by(InvoiceItem.id.asc()).all()

    vendor = db.query(Supplier).filter(
        Supplier.id == invoice.vendor_id
    ).first()

    po = None
    po_items = []
    if invoice.po_id:
        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == invoice.po_id
        ).first()
        po_items = db.query(PurchaseOrderItem).filter(
            PurchaseOrderItem.po_id == invoice.po_id
        ).order_by(PurchaseOrderItem.id.asc()).all()

    payments = [
        PaymentService.serialize(db, p) for p in invoice.payments
    ]

    return templates.TemplateResponse(
        request=request,
        name="invoice_details.html",
        context={
            "request": request,
            "invoice": invoice,
            "items": items,
            "vendor": vendor,
            "po": po,
            "po_items": po_items,
            "payments": payments
        }
    )
