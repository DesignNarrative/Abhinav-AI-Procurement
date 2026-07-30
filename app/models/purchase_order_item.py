from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Text,
    ForeignKey
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.database import Base


class PurchaseOrderItem(Base):
    """
    Line item on a Purchase Order.

    Snapshotted from the awarded quotation item at PO generation time so
    the ordered material, quantity, brand, specs and landed rate are
    frozen on the PO regardless of later quotation revisions.
    """
    __tablename__ = "purchase_order_items"

    id = Column(Integer, primary_key=True, index=True)

    po_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False
    )

    # Traceability back to the source quotation / RFQ item (nullable so
    # the PO survives if those rows are ever removed).
    quotation_item_id = Column(
        Integer,
        ForeignKey("quotation_items.id", ondelete="SET NULL"),
        nullable=True
    )

    rfq_item_id = Column(
        Integer,
        ForeignKey("rfq_items.id", ondelete="SET NULL"),
        nullable=True
    )

    material_category = Column(String(255), nullable=True)
    material_name = Column(String(255), nullable=False)

    ordered_quantity = Column(Numeric(18, 3), nullable=False)
    unit = Column(String(50), nullable=False)

    brand = Column(String(255), nullable=True)
    specs = Column(JSONB, nullable=True, default=dict)

    # Commercial snapshot
    basic_rate = Column(Numeric(18, 3), default=0.0, nullable=False)
    discount_percent = Column(Numeric(5, 2), default=0.0, nullable=False)
    tax_percent = Column(Numeric(5, 2), default=0.0, nullable=False)
    freight_amount = Column(Numeric(18, 3), default=0.0, nullable=False)

    final_landed_rate = Column(Numeric(18, 3), default=0.0, nullable=False)
    total_amount = Column(Numeric(18, 3), default=0.0, nullable=False)

    remarks = Column(Text, nullable=True)

    purchase_order = relationship(
        "PurchaseOrder",
        back_populates="items"
    )
