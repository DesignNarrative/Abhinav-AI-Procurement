import re

from typing import Optional

from datetime import datetime

from pydantic import (
    BaseModel,
    EmailStr,
    field_validator
)


class SupplierCreate(BaseModel):

    company_name: str

    principal_business: Optional[str] = None

    gst_number: Optional[str] = None


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
        gst_pattern = (
            r'^[0-9]{2}'
            r'[A-Z]{5}'
            r'[0-9]{4}'
            r'[A-Z]{1}'
            r'[A-Z0-9]{1}'
            r'Z'
            r'[0-9A-Z]{1}$'
        )

        value = value.upper()

        if not re.match(
            gst_pattern,
            value
        ):
            raise ValueError(
                "Invalid GST Number"
            )

        return value


    @field_validator("whatsapp_number")
    @classmethod
    def validate_whatsapp_number(
        cls,
        value
    ):

        if not value.isdigit():

            raise ValueError(
                "WhatsApp number must contain digits only"
            )

        if len(value) != 10:

            raise ValueError(
                "WhatsApp number must be exactly 10 digits"
            )

        return value


    @field_validator("bank_account_number")
    @classmethod
    def validate_account_number(
        cls,
        value
    ):

        if not value.isdigit():

            raise ValueError(
                "Bank account number must contain digits only"
            )

        return value


    @field_validator("bank_ifsc")
    @classmethod
    def validate_ifsc(
        cls,
        value
    ):

        value = value.upper()

        ifsc_pattern = (
            r'^[A-Z]{4}'
            r'0'
            r'[A-Z0-9]{6}$'
        )

        if not re.match(
            ifsc_pattern,
            value
        ):
            raise ValueError(
                "Invalid IFSC Code"
            )

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
    
    
    