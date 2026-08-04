from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.services.supplier_service import SupplierService
from app.services.excel_service import ExcelService
from app.models.supplier import Supplier

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"]
)

templates = Jinja2Templates(
    directory="app/templates"
)


@router.get(
    "/",
    response_class=HTMLResponse
)
def dashboard(
    request: Request,
    db: Session = Depends(get_db)
):

    stats = SupplierService.get_dashboard_stats(db)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "stats": stats
        }
    )


# =====================================================
# Supplier Management
# =====================================================

@router.get(
    "/suppliers",
    response_class=HTMLResponse
)
def supplier_management(
    request: Request,
    db: Session = Depends(get_db),
    search: str = "",
    status: str = "",
    category: str = ""
):

    query = db.query(Supplier)

    if search:
        query = query.filter(
            Supplier.company_name.ilike(f"%{search}%")
        )

    if status:
        query = query.filter(
            Supplier.registration_status == status
        )

    if category:
        query = query.filter(
            Supplier.supplier_category.ilike(category)
        )

    suppliers = query.order_by(
        Supplier.created_at.desc()
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="supplier_management.html",
        context={
            "request": request,
            "suppliers": suppliers,
            "search": search,
            "status": status,
            "category": category
        }
    )


# =====================================================
# Export Excel
# =====================================================

@router.get("/suppliers/export")
def export_suppliers(
    db: Session = Depends(get_db)
):

    suppliers = db.query(
        Supplier
    ).order_by(
        Supplier.company_name
    ).all()

    excel_file = ExcelService.export_suppliers(
        suppliers
    )

    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition":
            "attachment; filename=Suppliers.xlsx"
        }
    )


# =====================================================
# Supplier Details
# IMPORTANT:
# This MUST be the LAST supplier route.
# =====================================================

@router.get(
    "/suppliers/{supplier_id}",
    response_class=HTMLResponse
)
def supplier_details(
    supplier_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    supplier = db.query(
        Supplier
    ).filter(
        Supplier.id == supplier_id
    ).first()

    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found"
        )

    return templates.TemplateResponse(
        request=request,
        name="supplier_details.html",
        context={
            "request": request,
            "supplier": supplier
        }
    )


# =====================================================
# WhatsApp Inbox Page
# =====================================================

@router.get(
    "/inbox/",
    response_class=HTMLResponse
)
def whatsapp_inbox_page(
    request: Request
):
    return templates.TemplateResponse(
        request=request,
        name="whatsapp_inbox.html",
        context={"request": request}
    )