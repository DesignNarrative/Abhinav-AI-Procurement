import logging
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.erp_sync_queue import ERPSyncQueue
from app.services.erp_connector import get_connector

logger = logging.getLogger(__name__)


VALID_ENTITY_TYPES = [
    "Supplier", "RFQ", "Quotation", "PurchaseOrder",
    "GRN", "Invoice", "Payment"
]

# Give up automatic retries after this many attempts (stays FAILED, can be
# retried manually from the UI).
MAX_ATTEMPTS = 5


class ERPSyncService:

    # =====================================================
    # Enqueue an entity for sync (idempotent)
    # =====================================================

    @staticmethod
    def enqueue(
        db: Session,
        entity_type: str,
        entity_id: int,
        payload: dict = None,
        idempotency_key: str = None
    ) -> ERPSyncQueue:
        if entity_type not in VALID_ENTITY_TYPES:
            raise ValueError(f"Invalid entity type: {entity_type}")

        key = idempotency_key or f"{entity_type}:{entity_id}"

        existing = db.query(ERPSyncQueue).filter(
            ERPSyncQueue.idempotency_key == key
        ).first()
        if existing:
            # Already queued — refresh payload if still pending / failed.
            if existing.status in ("PENDING", "FAILED"):
                existing.payload = payload or existing.payload
                existing.status = "PENDING"
                db.commit()
                db.refresh(existing)
            return existing

        entry = ERPSyncQueue(
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
            idempotency_key=key,
            status="PENDING"
        )
        db.add(entry)
        try:
            db.commit()
            db.refresh(entry)
        except IntegrityError:
            # Concurrent insert with the same key — return the winner.
            db.rollback()
            return db.query(ERPSyncQueue).filter(
                ERPSyncQueue.idempotency_key == key
            ).first()
        return entry

    # =====================================================
    # Process a single queue entry (one push attempt)
    # =====================================================

    @staticmethod
    def process_entry(db: Session, entry_id: int) -> ERPSyncQueue:
        entry = db.query(ERPSyncQueue).filter(
            ERPSyncQueue.id == entry_id
        ).first()
        if not entry:
            raise ValueError("Queue entry not found")

        if entry.status == "SYNCED":
            return entry

        connector = get_connector()
        entry.attempt_count = (entry.attempt_count or 0) + 1
        entry.last_attempt_at = datetime.now()

        try:
            result = connector.push(
                entry.entity_type, entry.entity_id, entry.payload or {}
            )
        except Exception as e:  # connector should not raise, but be safe
            result = None
            logger.error("ERP push raised: %s", e, exc_info=True)
            entry.status = "FAILED"
            entry.last_error = str(e)
            db.commit()
            db.refresh(entry)
            return entry

        if result and result.success:
            entry.status = "SYNCED"
            entry.erp_reference = result.reference
            entry.last_error = None
            entry.synced_at = datetime.now()
        else:
            entry.status = "FAILED"
            entry.last_error = (
                result.error if result else "Unknown connector error"
            )

        db.commit()
        db.refresh(entry)
        return entry

    # =====================================================
    # Process all pending / retryable entries (backoff by attempt cap)
    # =====================================================

    @staticmethod
    def process_pending(db: Session) -> dict:
        entries = db.query(ERPSyncQueue).filter(
            ERPSyncQueue.status.in_(["PENDING", "FAILED"]),
            ERPSyncQueue.attempt_count < MAX_ATTEMPTS
        ).order_by(ERPSyncQueue.created_at.asc()).all()

        synced = 0
        failed = 0
        for entry in entries:
            ERPSyncService.process_entry(db, entry.id)
            db.refresh(entry)
            if entry.status == "SYNCED":
                synced += 1
            else:
                failed += 1

        return {
            "processed": len(entries),
            "synced": synced,
            "failed": failed
        }

    # =====================================================
    # Manual retry (resets a FAILED entry for another attempt)
    # =====================================================

    @staticmethod
    def retry(db: Session, entry_id: int) -> ERPSyncQueue:
        entry = db.query(ERPSyncQueue).filter(
            ERPSyncQueue.id == entry_id
        ).first()
        if not entry:
            raise ValueError("Queue entry not found")
        if entry.status == "SYNCED":
            raise ValueError("Entry is already synced.")
        entry.status = "PENDING"
        db.commit()
        return ERPSyncService.process_entry(db, entry_id)

    # =====================================================
    # Queries
    # =====================================================

    @staticmethod
    def serialize(entry: ERPSyncQueue) -> dict:
        return {
            "id": entry.id,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "status": entry.status,
            "attempt_count": entry.attempt_count,
            "last_error": entry.last_error,
            "erp_reference": entry.erp_reference,
            "idempotency_key": entry.idempotency_key,
            "last_attempt_at": (
                entry.last_attempt_at.isoformat()
                if entry.last_attempt_at else None
            ),
            "synced_at": (
                entry.synced_at.isoformat() if entry.synced_at else None
            ),
            "created_at": entry.created_at.isoformat()
        }

    @staticmethod
    def list_entries(db: Session, status: str = None) -> list:
        q = db.query(ERPSyncQueue)
        if status:
            q = q.filter(ERPSyncQueue.status == status)
        entries = q.order_by(ERPSyncQueue.created_at.desc()).all()
        return [ERPSyncService.serialize(e) for e in entries]

    @staticmethod
    def status_for(db: Session, entity_type: str, entity_id: int) -> dict:
        entry = db.query(ERPSyncQueue).filter(
            ERPSyncQueue.entity_type == entity_type,
            ERPSyncQueue.entity_id == entity_id
        ).order_by(ERPSyncQueue.created_at.desc()).first()
        if not entry:
            return {"status": "NOT_QUEUED"}
        return ERPSyncService.serialize(entry)
