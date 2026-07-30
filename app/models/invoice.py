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


class Invoice(Base):
    """
    Vendor invoice raised against a Purchase Order.

    Invoices can be entered manually or captured automatically from the
    document-intelligence pipeline (WhatsApp / uploaded INVOICE documents).
    A 3-way match (invoice vs PO vs GRN) is stored on the record so the
    verification result is auditable and never recomputed silently.
    """
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)

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

    # Traceability to the source document (if captured from the pipeline).
    document_uuid = Column(String(64), nullable=True, index=True)

    invoice_number = Column(String(100), nullable=False, index=True)
    invoice_date = Column(Date, nullable=True)

    # Commercial amounts
    taxable_amount = Column(Numeric(18, 3), default=0.0, nullable=False)
    cgst_amount = Column(Numeric(18, 3), default=0.0, nullable=False)
    sgst_amount = Column(Numeric(18, 3), default=0.0, nullable=False)
    igst_amount = Column(Numeric(18, 3), default=0.0, nullable=False)
    total_tax_amount = Column(Numeric(18, 3), default=0.0, nullable=False)
    freight_amount = Column(Numeric(18, 3), default=0.0, nullable=False)
    invoice_amount = Column(Numeric(18, 3), default=0.0, nullable=False)

    file_path = Column(String(500), nullable=True)

    # Received, Verified, Mismatch, Approved, Paid
    status = Column(String(50), default="Received", nullable=False)

    # 3-way match result (Matched / Mismatch / Not Checked) + notes
    match_status = Column(String(50), default="Not Checked", nullable=False)
    match_notes = Column(Text, nullable=True)

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
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan"
    )
    payments = relationship(
        "Payment",
        back_populates="invoice",
        cascade="all, delete-orphan"
    )
    vendor = relationship("Supplier")
    purchase_order = relationship("PurchaseOrder")
