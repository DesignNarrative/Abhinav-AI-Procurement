from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Text,
    ForeignKey
)
from sqlalchemy.orm import relationship

from app.database.database import Base


class InvoiceItem(Base):
    """
    Line item on a vendor invoice.

    Optionally linked to the PO item it bills against so the 3-way match
    can compare invoiced quantity / rate against the ordered snapshot.
    Kept independent of the PO item so an invoice can still be stored even
    when the pipeline cannot confidently map every line.
    """
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)

    invoice_id = Column(
        Integer,
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False
    )

    # Link back to the ordered PO item (nullable when unmatched).
    po_item_id = Column(
        Integer,
        ForeignKey("purchase_order_items.id", ondelete="SET NULL"),
        nullable=True
    )

    material_name = Column(String(255), nullable=False)
    unit = Column(String(50), nullable=True)

    invoiced_quantity = Column(Numeric(18, 3), default=0.0, nullable=False)
    rate = Column(Numeric(18, 3), default=0.0, nullable=False)
    tax_percent = Column(Numeric(5, 2), default=0.0, nullable=False)
    amount = Column(Numeric(18, 3), default=0.0, nullable=False)

    remarks = Column(Text, nullable=True)

    invoice = relationship("Invoice", back_populates="items")
    po_item = relationship("PurchaseOrderItem")
