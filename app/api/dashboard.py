from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.services.supplier_service import SupplierService
from app.services.excel_service import ExcelService
from app.models.supplier import Supplier

# Import all related models so SQLAlchemy mapper resolves correctly
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.purchase_order import PurchaseOrder
from app.models.requirement import Requirement

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

    # Procurement stats
    total_reqs = db.query(Requirement).count()
    active_reqs = db.query(Requirement).filter(
        Requirement.status.notin_(["COMPLETED", "CANCELLED"])
    ).count()
    open_rfqs = db.query(RFQ).filter(
        RFQ.status.notin_(["Closed", "Cancelled"])
    ).count()
    total_quotations = db.query(Quotation).count()
    active_pos = db.query(PurchaseOrder).filter(
        PurchaseOrder.status.notin_(["Delivered", "Cancelled"])
    ).count()

    recent_reqs = db.query(Requirement).order_by(Requirement.id.desc()).limit(5).all()
    recent_rfqs = db.query(RFQ).order_by(RFQ.id.desc()).limit(5).all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "stats": stats,
            "procurement": {
                "total_reqs": total_reqs,
                "active_reqs": active_reqs,
                "open_rfqs": open_rfqs,
                "total_quotations": total_quotations,
                "active_pos": active_pos,
            },
            "recent_reqs": recent_reqs,
            "recent_rfqs": recent_rfqs,
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

    query = db.query(Supplier).filter(Supplier.registration_status != "PENDING_REGISTRATION")

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
            Supplier.supplier_category.ilike(f"%{category}%")
        )

    suppliers = query.order_by(
        Supplier.created_at.desc()
    ).all()

    # Build unique category list by extracting from BOTH principal_business AND material_types
    # for every supplier — identical to registration logic so nothing is ever missed.
    from app.services.supplier_mapper import extract_categories
    all_suppliers = db.query(Supplier).filter(Supplier.registration_status != "PENDING_REGISTRATION").all()
    categories_set = set()
    for s in all_suppliers:
        cats = extract_categories(s.principal_business, s.material_types)
        categories_set.update(cats)
    categories = sorted(list(categories_set))

    return templates.TemplateResponse(
        request=request,
        name="supplier_management.html",
        context={
            "request": request,
            "suppliers": suppliers,
            "search": search,
            "status": status,
            "category": category,
            "categories": categories
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
