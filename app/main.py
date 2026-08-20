from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Auth
from app.api.auth import router as auth_router
from app.services.auth_service import decode_token, create_default_admin

from app.api.supplier import router as supplier_router
from app.api.upload import router as upload_router


# Import Models — import the __init__ to register ALL models with SQLAlchemy
import app.models  # noqa: F401 — registers all models so relationships resolve correctly
from app.models.supplier import Supplier
from app.models.supplier_conversation import SupplierConversation

from app.api.whatsapp import router as whatsapp_router

from app.api.dashboard import router as dashboard_router

from app.api.requirement import router as requirement_router
from app.api.requirement_dashboard import router as requirement_dashboard_router

from app.api.vendor_dashboard import router as vendor_dashboard_router
from app.api.rfq import router as rfq_router
from app.api.rfq_dashboard import router as rfq_dashboard_router
from app.api.quotation import router as quotation_router
from app.api.quotation_dashboard import router as quotation_dashboard_router
from app.api.document_intelligence import router as document_intelligence_router
from app.api.document_intelligence_dashboard import router as document_intelligence_dashboard_router
from app.api.comparison import router as comparison_router
from app.api.negotiation import router as negotiation_router
from app.api.purchase_order import router as purchase_order_router
from app.api.delivery import router as delivery_router
from app.api.invoice import router as invoice_router
from app.api.payment import router as payment_router
from app.api.erp_sync import router as erp_sync_router
from app.api.reminder import router as reminder_router
from app.api.analytics import router as analytics_router
from app.api.inbox import router as inbox_router

from app.services.scheduler_service import start_scheduler, stop_scheduler

app = FastAPI(
    title="Abhinav Group AI Procurement Platform"
)

COOKIE_NAME = "procurement_token"


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """
    Protect all /dashboard/* routes.
    Webhook (/whatsapp/webhook) and /auth/* stay always public.
    """
    path = request.url.path

    # Public prefixes - never require login
    public_prefixes = [
        "/auth/",
        "/whatsapp/",
        "/static/",
        "/uploads/",
        "/suppliers/",
        "/docs",
        "/openapi",
        "/redoc",
    ]

    is_public = any(path.startswith(p) for p in public_prefixes) or path == "/"

    if not is_public and path.startswith("/dashboard"):
        token = request.cookies.get(COOKIE_NAME)
        if not token or not decode_token(token):
            return RedirectResponse(url="/auth/login", status_code=302)

    return await call_next(request)


app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads"
)


app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static"
)

# Routers
app.include_router(auth_router)
app.include_router(supplier_router)
app.include_router(upload_router)
app.include_router(whatsapp_router)
app.include_router(dashboard_router)
app.include_router(requirement_router)
app.include_router(requirement_dashboard_router)
app.include_router(vendor_dashboard_router)
app.include_router(rfq_router)
app.include_router(rfq_dashboard_router)
app.include_router(quotation_router)
app.include_router(quotation_dashboard_router)
app.include_router(document_intelligence_router)
app.include_router(document_intelligence_dashboard_router)
app.include_router(comparison_router)
app.include_router(negotiation_router)
app.include_router(purchase_order_router)
app.include_router(delivery_router)
app.include_router(invoice_router)
app.include_router(payment_router)
app.include_router(erp_sync_router)
app.include_router(reminder_router)
app.include_router(analytics_router)
app.include_router(inbox_router)


@app.on_event("startup")
def _start_reminder_scheduler():
    start_scheduler()


@app.on_event("startup")
def _migrate_delivery_status_column():
    from app.database.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("ALTER TABLE whatsapp_inbox_messages ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(50) DEFAULT 'sent'"))
        db.commit()
        print("[DATABASE] Altered whatsapp_inbox_messages table successfully (added delivery_status column).")
    except Exception as e:
        print(f"[DATABASE] Alter table failed or column already exists: {e}")
    finally:
        db.close()


@app.on_event("startup")
def _create_default_admin():
    from app.database.database import SessionLocal
    db = SessionLocal()
    try:
        create_default_admin(db)
    finally:
        db.close()


@app.on_event("shutdown")
def _stop_reminder_scheduler():
    stop_scheduler()


@app.on_event("startup")
def _backfill_supplier_categories():
    """
    On every startup, re-run extract_categories on every approved supplier whose
    principal_business or material_types fields are set and refresh supplier_category.
    This is safe, idempotent, and fixes any supplier whose categories are stale
    (registered before auto-calc was in place, or edited without recalculation).
    """
    from app.database.database import SessionLocal
    from app.services.supplier_mapper import extract_categories
    db = SessionLocal()
    try:
        suppliers = db.query(Supplier).filter(
            Supplier.registration_status != "PENDING_REGISTRATION"
        ).all()
        updated = 0
        for s in suppliers:
            if s.principal_business or s.material_types:
                cats = extract_categories(s.principal_business, s.material_types)
                new_cat = ", ".join(cats) if cats else None
                if s.supplier_category != new_cat:
                    s.supplier_category = new_cat
                    updated += 1
        if updated:
            db.commit()
            print(f"[STARTUP] Backfilled supplier_category for {updated} supplier(s).")
        else:
            print("[STARTUP] supplier_category backfill: all suppliers already up to date.")
    except Exception as e:
        db.rollback()
        print(f"[STARTUP] supplier_category backfill failed: {e}")
    finally:
        db.close()


@app.get("/")
def home():
    return RedirectResponse(url="/dashboard/", status_code=302)
