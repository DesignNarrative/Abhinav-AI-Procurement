from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey  # noqa: F401  (kept for parity; queue is loosely coupled)
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database.database import Base


class ERPSyncQueue(Base):
    """
    Outbound sync queue for pushing business entities to an ERP.

    The queue is deliberately decoupled from the source tables (it stores
    the entity type + id + a frozen payload) so it works for any ERP and
    survives even if the concrete connector is not yet decided. An
    idempotency key prevents the same logical change being queued twice.
    """
    __tablename__ = "erp_sync_queue"

    id = Column(Integer, primary_key=True, index=True)

    # Supplier, RFQ, Quotation, PurchaseOrder, GRN, Invoice, Payment
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)

    # Frozen snapshot of what should be pushed to the ERP.
    payload = Column(JSONB, nullable=True, default=dict)

    # Prevents duplicate queueing of the same logical change.
    idempotency_key = Column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )

    # PENDING, SYNCED, FAILED
    status = Column(String(20), default="PENDING", nullable=False, index=True)

    attempt_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)

    # Identifier returned by the ERP once synced (for traceability).
    erp_reference = Column(String(255), nullable=True)

    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
