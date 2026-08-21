from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    Numeric,
    ForeignKey,
    Date,
    Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base

class Quotation(Base):
    __tablename__ = "quotations"

    id = Column(Integer, primary_key=True, index=True)
    quotation_number = Column(String(50), unique=True, index=True, nullable=False)
    revision_number = Column(Integer, default=0, nullable=False)
    
    rfq_id = Column(Integer, ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False)
    vendor_id = Column(Integer, ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    
    is_latest = Column(Boolean, default=True, nullable=False)
    approved_for_comparison = Column(Boolean, default=False, nullable=False)
    
    date_received = Column(Date, nullable=False)
    validity_date = Column(Date, nullable=True)
    payment_terms = Column(String(255), nullable=True)
    delivery_timeline = Column(String(255), nullable=True)
    
    # Header level commercial data
    freight_amount_total = Column(Numeric(18, 3), default=0.0, nullable=False)
    loading_unloading_total = Column(Numeric(18, 3), default=0.0, nullable=False)
    grand_total = Column(Numeric(18, 3), default=0.0, nullable=False)
    
    attachment_path = Column(String(500), nullable=True)
    status = Column(String(50), default="Draft", nullable=False)
    creation_source = Column(String(50), default="MANUAL", nullable=False)
    
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

    items = relationship("QuotationItem", back_populates="quotation", cascade="all, delete-orphan")
    rfq = relationship("RFQ")
    vendor = relationship("Supplier")
