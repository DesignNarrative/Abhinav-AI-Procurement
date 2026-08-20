from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.ext.mutable import MutableDict

from app.database.database import Base


class SupplierQuotationConversation(Base):
    __tablename__ = "supplier_quotation_conversations"

    id = Column(Integer, primary_key=True, index=True)

    phone_number = Column(String(20), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)

    rfq_id = Column(Integer, ForeignKey("rfqs.id", ondelete="SET NULL"), nullable=True)

    conversation_status = Column(String(50), default="IN_PROGRESS", nullable=False)

    current_step = Column(String(100), nullable=False, default="awaiting_rfq_number")

    current_material_index = Column(Integer, default=1, nullable=False)

    collected_data = Column(
        MutableDict.as_mutable(JSONB),
        nullable=True,
        default=dict
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
