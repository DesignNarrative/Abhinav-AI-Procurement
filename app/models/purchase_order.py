from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    DateTime,
    Date,
    ForeignKey
)

from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database.database import Base


class PurchaseOrder(Base):
    """
    Purchase Order raised against an awarded quotation.

    Commercial values are snapshotted from the awarded quotation at
    generation time (same snapshot pattern as RFQ generation) so the PO
    is a permanent, self-contained record even if quotations change later.
    """
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, index=True)

    po_number = Column(
        String(50),
        unique=True,
        index=True,
        nullable=False
    )

    # Traceability links back to the award / RFQ / vendor.
    award_id = Column(
        Integer,
        ForeignKey("rfq_awards.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    rfq_id = Column(
        Integer,
        ForeignKey("rfqs.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    quotation_id = Column(
        Integer,
        ForeignKey("quotations.id", ondelete="SET NULL"),
        nullable=True
    )

    vendor_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    po_date = Column(Date, nullable=True)

    # Addresses / delivery
    billing_address = Column(Text, nullable=True)
    shipping_address = Column(Text, nullable=True)
    site_name = Column(String(255), nullable=True)

    # Site contact for delivery coordination
    contact_person = Column(String(255), nullable=True)
    contact_number = Column(String(50), nullable=True)

    # Commercial terms
    payment_terms = Column(String(255), nullable=True)
    delivery_timeline = Column(String(255), nullable=True)
    penalty_terms = Column(Text, nullable=True)
    terms_conditions = Column(Text, nullable=True)

    # Totals snapshotted from the awarded quotation
    freight_total = Column(Numeric(18, 3), default=0.0, nullable=False)
    loading_unloading_total = Column(Numeric(18, 3), default=0.0, nullable=False)
    grand_total = Column(Numeric(18, 3), default=0.0, nullable=False)

    # Draft, Pending Approval, Approved, Sent, Accepted, Rejected,
    # Cancelled, Closed
    status = Column(String(50), default="Draft", nullable=False)

    pdf_path = Column(String(500), nullable=True)
    whatsapp_status = Column(String(50), nullable=True)

    approved_by = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)

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

    items = relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan"
    )
    vendor = relationship("Supplier")
    rfq = relationship("RFQ")
    quotation = relationship("Quotation")
    award = relationship("RFQAward")
