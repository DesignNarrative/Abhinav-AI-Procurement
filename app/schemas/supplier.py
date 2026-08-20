import re

from typing import Optional

from datetime import datetime

from pydantic import (
    BaseModel,
    EmailStr,
    field_validator
)


class SupplierCreate(BaseModel):
    company_name: Optional[str] = None
    principal_business: Optional[str] = None
    gst_number: Optional[str] = None
    registered_address: Optional[str] = None
    contact_person_name: Optional[str] = None
    contact_person_email: Optional[EmailStr] = None
    whatsapp_number: Optional[str] = None
    supplier_category: Optional[str] = None
    material_types: Optional[str] = None
    bank_name: Optional[str] = None
    beneficiary_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None

    branch_name: Optional[str] = None

    is_msme: bool = False

    msme_number: Optional[str] = None

    msme_certificate_path: Optional[str] = None

    gst_certificate_path: Optional[str] = None

    references: Optional[str] = None

    authorized_person_name: Optional[str] = None

    designation: Optional[str] = None

    declaration_accepted: bool = False


    @field_validator("company_name")
    @classmethod
    def validate_company_name(
        cls,
        value
    ):
        if not value:
            return value
        value = value.strip()

        if len(value) < 3:
            raise ValueError(
                "Company name must be at least 3 characters"
            )

        return value


    @field_validator("gst_number")
    @classmethod
    def validate_gst(
        cls,
        value
    ):
        if value:
            return value.strip().upper()
        return value


    @field_validator("whatsapp_number")
    @classmethod
    def validate_whatsapp_number(
        cls,
        value
    ):
        if value:
            return "".join(c for c in value if c.isdigit())
        return value


    @field_validator("bank_account_number")
    @classmethod
    def validate_account_number(
        cls,
        value
    ):
        if value:
            return value.strip()
        return value


    @field_validator("bank_ifsc")
    @classmethod
    def validate_ifsc(
        cls,
        value
    ):
        if value:
            return value.strip().upper()
        return value


class SupplierResponse(BaseModel):

    id: int

    supplier_code: Optional[str] = None

    company_name: str

    principal_business: Optional[str] = None

    gst_number: str

    registered_address: str

    contact_person_name: str

    contact_person_email: Optional[EmailStr] = None

    whatsapp_number: str

    supplier_category: Optional[str] = None

    material_types: Optional[str] = None

    bank_name: str

    beneficiary_name: str

    bank_account_number: str

    bank_ifsc: str

    branch_name: Optional[str] = None

    is_msme: bool

    msme_number: Optional[str] = None

    msme_certificate_path: Optional[str] = None

    gst_certificate_path: Optional[str] = None

    references: Optional[str] = None

    authorized_person_name: Optional[str] = None

    designation: Optional[str] = None

    declaration_accepted: bool

    registration_status: str

    approval_remarks: Optional[str] = None

    erp_sync_status: Optional[str] = None

    is_active: bool

    created_at: datetime

    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class SupplierListResponse(BaseModel):

    id: int

    supplier_code: Optional[str] = None

    company_name: str

    contact_person_name: str

    whatsapp_number: str

    supplier_category: Optional[str] = None

    registration_status: str

    created_at: datetime

    model_config = {
        "from_attributes": True
    }
    
class SupplierApprovalRequest(BaseModel):

    remarks: str


class SupplierRejectionRequest(BaseModel):

    remarks: str


class SupplierUpdate(BaseModel):
    """All PM-editable supplier fields. Every field is Optional — only send what changed."""

    company_name: Optional[str] = None
    principal_business: Optional[str] = None
    gst_number: Optional[str] = None
    registered_address: Optional[str] = None
    supplier_category: Optional[str] = None
    material_types: Optional[str] = None

    contact_person_name: Optional[str] = None
    contact_person_email: Optional[str] = None
    whatsapp_number: Optional[str] = None

    bank_name: Optional[str] = None
    beneficiary_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    branch_name: Optional[str] = None

    is_msme: Optional[bool] = None
    msme_number: Optional[str] = None
    msme_certificate_path: Optional[str] = None
    gst_certificate_path: Optional[str] = None

    authorized_person_name: Optional[str] = None
    designation: Optional[str] = None

    