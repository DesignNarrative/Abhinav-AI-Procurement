from fastapi import FastAPI


from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.supplier import router as supplier_router
from app.api.upload import router as upload_router


# Import Models
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

from app.services.scheduler_service import start_scheduler, stop_scheduler

app = FastAPI(
    title="Abhinav Group Supplier Registration System"
)





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


@app.on_event("startup")
def _start_reminder_scheduler():
    start_scheduler()


@app.on_event("shutdown")
def _stop_reminder_scheduler():
    stop_scheduler()


@app.get("/")
def home():
    return {
        "status": "running",
        "project": "Supplier Registration"
    }