from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Boolean
)
from sqlalchemy.sql import func

from app.database.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    supplier_code = Column(
        String(20),
        unique=True,
        nullable=True
    )

    company_name = Column(
        String(255),
        nullable=False
    )

    principal_business = Column(
        Text,
        nullable=True
    )

    gst_number = Column(
        String(15),
        unique=True,
        nullable=True
    )


    registered_address = Column(
        Text,
        nullable=False
    )

    contact_person_name = Column(
        String(255),
        nullable=False
    )

    contact_person_email = Column(
        String(255),
        nullable=True
    )

    whatsapp_number = Column(
        String(15),
        nullable=False
    )

    supplier_category = Column(
        String(255),
        nullable=True
    )

    material_types = Column(
        Text,
        nullable=True
    )

    bank_name = Column(
        String(255),
        nullable=False
    )

    beneficiary_name = Column(
        String(255),
        nullable=False
    )

    bank_account_number = Column(
        String(50),
        nullable=False
    )

    bank_ifsc = Column(
        String(20),
        nullable=False
    )

    branch_name = Column(
        String(255),
        nullable=True
    )

    is_msme = Column(
        Boolean,
        default=False
    )

    msme_number = Column(
        String(100),
        nullable=True
    )

    msme_certificate_path = Column(
        Text,
        nullable=True
    )

    gst_certificate_path = Column(
        Text,
        nullable=True
    )

    references = Column(
        Text,
        nullable=True
    )

    authorized_person_name = Column(
        String(255),
        nullable=True
    )

    designation = Column(
        String(255),
        nullable=True
    )

    declaration_accepted = Column(
        Boolean,
        default=False
    )

    registration_status = Column(
        String(50),
        default="PENDING"
    )

    approval_remarks = Column(
        Text,
        nullable=True
    )

    erp_sync_status = Column(
        String(50),
        default="NOT_SYNCED"
    )

    is_active = Column(
        Boolean,
        default=True
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