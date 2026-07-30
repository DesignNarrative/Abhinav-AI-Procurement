from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base


class ReminderLog(Base):
    """
    Log of every automated reminder sent (or attempted).
    The unique dedup_key guarantees a reminder is never sent twice.
    """
    __tablename__ = "reminders_log"

    id = Column(Integer, primary_key=True, index=True)

    # RFQ_NO_REPLY_12H / RFQ_NO_REPLY_24H / RFQ_NO_REPLY_48H /
    # PAYMENT_DUE_TOMORROW / PAYMENT_OVERDUE / QUOTATION_EXPIRY
    reminder_type = Column(String(50), nullable=False, index=True)

    # RFQ / Payment / Quotation
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False, index=True)

    vendor_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True
    )

    # Uniqueness guard, e.g. "RFQ_NO_REPLY_24H:12:5"
    dedup_key = Column(String(255), unique=True, index=True, nullable=False)

    recipient = Column(String(30), nullable=True)
    message = Column(Text, nullable=True)

    # SENT / FAILED / LOGGED (no recipient configured)
    status = Column(String(20), default="SENT", nullable=False)
    error = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    vendor = relationship("Supplier")
