from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    Boolean,
    ForeignKey
)

from sqlalchemy.orm import relationship

from app.database.database import Base


class DeliveryItem(Base):
    """
    GRN line: quantity actually received against one PO item in a delivery.

    Multiple DeliveryItem rows (across deliveries) can reference the same
    PO item for partial deliveries; the cumulative received quantity is
    used to decide when the PO item is fully received.
    """
    __tablename__ = "delivery_items"

    id = Column(Integer, primary_key=True, index=True)

    delivery_id = Column(
        Integer,
        ForeignKey("deliveries.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    po_item_id = Column(
        Integer,
        ForeignKey("purchase_order_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    received_quantity = Column(Numeric(18, 3), default=0.0, nullable=False)

    quality_ok = Column(Boolean, default=True, nullable=False)

    damage_notes = Column(Text, nullable=True)

    photo_path = Column(String(500), nullable=True)

    delivery = relationship("Delivery", back_populates="items")
    po_item = relationship("PurchaseOrderItem")
