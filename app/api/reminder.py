from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.services.reminder_service import ReminderService
from app.services.scheduler_service import scheduler_running

router = APIRouter(tags=["Reminders"])

templates = Jinja2Templates(directory="app/templates")


# =====================================================
# JSON API
# =====================================================

@router.post("/reminders/run")
def run_reminders_now(db: Session = Depends(get_db)):
    """Manually trigger a full reminder cycle."""
    return ReminderService.run_all(db)


@router.get("/reminders/log")
def reminders_log(limit: int = 200, db: Session = Depends(get_db)):
    return {
        "scheduler_running": scheduler_running(),
        "entries": ReminderService.list_entries(db, limit)
    }


# =====================================================
# HTML Dashboard
# =====================================================

@router.get("/dashboard/reminders", response_class=HTMLResponse)
def reminders_page(request: Request, db: Session = Depends(get_db)):
    entries = ReminderService.list_entries(db)
    return templates.TemplateResponse(
        request=request,
        name="reminders_log.html",
        context={
            "request": request,
            "entries": entries,
            "scheduler_running": scheduler_running()
        }
    )
