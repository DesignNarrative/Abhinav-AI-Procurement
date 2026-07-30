from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    DateTime,
    ForeignKey
)

from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database.database import Base


class Negotiation(Base):
    """
    One negotiation round with a vendor on an RFQ.

    Append-only: rounds are never edited or deleted so the complete
    negotiation history (who offered what, when, and why) is preserved
    forever for audit.
    """
    __tablename__ = "negotiations"

    id = Column(Integer, primary_key=True, index=True)

    rfq_id = Column(
        Integer,
        ForeignKey("rfqs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    vendor_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # The quotation revision this round was negotiated against.
    quotation_id = Column(
        Integer,
        ForeignKey("quotations.id", ondelete="SET NULL"),
        nullable=True
    )

    # Sequential per RFQ + vendor: 1, 2, 3...
    round_number = Column(Integer, nullable=False, default=1)

    # WhatsApp, Call, Email, In Person
    channel = Column(String(50), nullable=False, default="Call")

    # Vendor's price at the start of this round
    original_price = Column(Numeric(18, 3), nullable=True)

    # Our counter offer / target
    counter_price = Column(Numeric(18, 3), nullable=True)

    # Price the vendor finally agreed to in this round (if any)
    agreed_price = Column(Numeric(18, 3), nullable=True)

    # Free-text call summary / WhatsApp gist / notes
    summary = Column(Text, nullable=True)

    # Pending, Agreed, Rejected, Revised Quotation Expected
    outcome = Column(String(50), nullable=False, default="Pending")

    created_by = Column(String(255), nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    rfq = relationship("RFQ")
    vendor = relationship("Supplier")
    quotation = relationship("Quotation")
