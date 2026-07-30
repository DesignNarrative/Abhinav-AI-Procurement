from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.schemas.erp_sync import ERPEnqueue
from app.services.erp_sync_service import ERPSyncService
from app.services.erp_connector import get_connector

router = APIRouter(tags=["ERP Sync"])

templates = Jinja2Templates(directory="app/templates")


# =====================================================
# JSON API
# =====================================================

@router.post("/erp-sync/enqueue")
def enqueue(payload: ERPEnqueue, db: Session = Depends(get_db)):
    try:
        entry = ERPSyncService.enqueue(
            db=db,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            payload=payload.payload,
            idempotency_key=payload.idempotency_key
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ERPSyncService.serialize(entry)


@router.post("/erp-sync/enqueue-and-push")
def enqueue_and_push(payload: ERPEnqueue, db: Session = Depends(get_db)):
    """One-click 'Sync to ERP': queue the entity and push immediately."""
    try:
        entry = ERPSyncService.enqueue(
            db=db,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            payload=payload.payload,
            idempotency_key=payload.idempotency_key
        )
        entry = ERPSyncService.process_entry(db, entry.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ERPSyncService.serialize(entry)


@router.post("/erp-sync/process")
def process_pending(db: Session = Depends(get_db)):
    return ERPSyncService.process_pending(db)


@router.post("/erp-sync/{entry_id}/retry")
def retry_entry(entry_id: int, db: Session = Depends(get_db)):
    try:
        entry = ERPSyncService.retry(db, entry_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ERPSyncService.serialize(entry)


@router.get("/erp-sync/queue")
def list_queue(status: str = None, db: Session = Depends(get_db)):
    return {
        "connector": get_connector().name,
        "entries": ERPSyncService.list_entries(db, status)
    }


@router.get("/erp-sync/status/{entity_type}/{entity_id}")
def entity_status(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db)
):
    return ERPSyncService.status_for(db, entity_type, entity_id)


# =====================================================
# HTML Dashboard
# =====================================================

@router.get("/dashboard/erp-sync", response_class=HTMLResponse)
def erp_sync_page(request: Request, db: Session = Depends(get_db)):
    entries = ERPSyncService.list_entries(db)
    return templates.TemplateResponse(
        request=request,
        name="erp_sync.html",
        context={
            "request": request,
            "entries": entries,
            "connector": get_connector().name
        }
    )
