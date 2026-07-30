from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey
)

from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database.database import Base


class RFQAward(Base):
    """
    Final vendor selection (award) for an RFQ.

    One award per RFQ — created after quotation comparison and
    (optional) negotiation. Stores the complete audit trail:
    who selected, why, and which quotation revision won.
    """
    __tablename__ = "rfq_awards"

    id = Column(Integer, primary_key=True, index=True)

    rfq_id = Column(
        Integer,
        ForeignKey("rfqs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True
    )

    quotation_id = Column(
        Integer,
        ForeignKey("quotations.id", ondelete="CASCADE"),
        nullable=False
    )

    vendor_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False
    )

    # Lowest cost, Best value, Fastest delivery, Preferred supplier,
    # Emergency, Director approval, Previous relationship, Single source
    selection_reason = Column(String(100), nullable=False)

    remarks = Column(Text, nullable=True)

    approved_by = Column(String(255), nullable=False)

    awarded_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    rfq = relationship("RFQ")
    quotation = relationship("Quotation")
    vendor = relationship("Supplier")
