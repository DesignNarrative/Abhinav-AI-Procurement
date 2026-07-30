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


class Payment(Base):
    """
    A payment (or scheduled payment) against a vendor invoice / PO.

    One invoice can have several payment entries (advance, part payments,
    final settlement). The due date is computed from the PO payment terms
    and the status reflects the outstanding lifecycle so the outstanding /
    overdue dashboard can be derived directly from these rows.
    """
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)

    invoice_id = Column(
        Integer,
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    po_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    vendor_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Advance, 50%, Full, Credit, Part
    payment_type = Column(String(50), default="Full", nullable=False)

    amount = Column(Numeric(18, 3), default=0.0, nullable=False)

    due_date = Column(Date, nullable=True)
    paid_date = Column(Date, nullable=True)

    # Bank / UTR / cheque reference
    reference = Column(String(255), nullable=True)

    # Pending, Due, Overdue, Partial, Paid
    status = Column(String(50), default="Pending", nullable=False)

    remarks = Column(Text, nullable=True)

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

    invoice = relationship("Invoice", back_populates="payments")
    purchase_order = relationship("PurchaseOrder")
    vendor = relationship("Supplier")
