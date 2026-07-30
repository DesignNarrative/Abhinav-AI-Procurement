from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base

class RFQ(Base):
    __tablename__ = "rfqs"

    id = Column(Integer, primary_key=True, index=True)
    rfq_number = Column(String(50), unique=True, index=True)
    project_name = Column(String(255), nullable=False)
    site_name = Column(String(255), nullable=False)
    delivery_location = Column(String(255), nullable=False)
    payment_terms = Column(String(255), nullable=True)

    # Optional requirement-context fields carried over from the merged
    # Requirements module. All nullable for backward compatibility.
    priority = Column(String(20), nullable=True)
    required_date = Column(String(50), nullable=True)
    purpose = Column(Text, nullable=True)
    
    # Draft, Pending Approval, Approved, Sent, Vendor Viewed, Vendor Responded, Quotation Received, Negotiation, Closed, Cancelled
    status = Column(String(50), default="Draft")
    
    created_by = Column(String(255), nullable=False)

    # Optional link back to the source Requirement this RFQ was generated from.
    # Nullable for backward compatibility: manually created RFQs leave this NULL.
    requirement_id = Column(
        Integer,
        ForeignKey("requirements.id"),
        nullable=True
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

    items = relationship("RFQItem", back_populates="rfq", cascade="all, delete-orphan")
    vendors = relationship("RFQVendor", back_populates="rfq", cascade="all, delete-orphan")

    # One-directional link to the source requirement (no back_populates to avoid
    # touching the Requirement model). Used only for traceability display.
    requirement = relationship("Requirement")
