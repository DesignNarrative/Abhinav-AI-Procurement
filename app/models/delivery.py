from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Date,
    ForeignKey
)

from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database.database import Base


class Delivery(Base):
    """
    A single dispatch / delivery event against a Purchase Order.

    One PO can have many Delivery records (partial deliveries supported).
    Each delivery carries its own GRN line items (received quantities and
    quality confirmation) captured by the site engineer.
    """
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)

    po_id = Column(
        Integer,
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    dispatch_date = Column(Date, nullable=True)
    eta = Column(Date, nullable=True)

    vehicle_number = Column(String(50), nullable=True)
    driver_name = Column(String(255), nullable=True)
    driver_number = Column(String(50), nullable=True)

    # LR / consignment copy upload path
    lr_copy_path = Column(String(500), nullable=True)

    # Dispatched, In Transit, Delivered, Partially Delivered,
    # Short Supply, Damaged, Rejected, Replacement
    status = Column(String(50), default="Dispatched", nullable=False)

    # GRN confirmation (site engineer)
    confirmed_by = Column(String(255), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

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

    items = relationship(
        "DeliveryItem",
        back_populates="delivery",
        cascade="all, delete-orphan"
    )
    purchase_order = relationship("PurchaseOrder")
