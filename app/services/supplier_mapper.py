def map_conversation_to_supplier(data: dict):

    is_msme_value = str(
        data.get("is_msme", "")
    ).upper()

    declaration_value = str(
        data.get("declaration_accepted", "")
    ).upper()

    return {

        "company_name":
            data.get("company_name"),

        "principal_business":
            data.get("principal_business"),

        "gst_number":
            data.get("gst_number"),

        "registered_address":
            data.get("registered_address"),

        "contact_person_name":
            data.get("contact_person_name"),

        "contact_person_email":
            None
            if data.get("contact_person_email") in (None, "SKIP", "skip")
            else data.get("contact_person_email"),

        "whatsapp_number":
            data.get("whatsapp_number"),

        "material_types":
            data.get("material_types"),

        "bank_name":
            data.get("bank_name"),

        "beneficiary_name":
            data.get("beneficiary_name"),

        "bank_account_number":
            data.get("bank_account_number"),

        "bank_ifsc":
            data.get("bank_ifsc"),

        "branch_name":
            data.get("branch_name"),

        "is_msme":
            is_msme_value == "YES"
            or data.get("is_msme") is True,

        "msme_number":
            None
            if str(data.get("msme_number", "")).upper() in ("SKIP", "NONE", "")
            else data.get("msme_number"),

        "msme_certificate_path":
            None
            if str(data.get("msme_certificate_path", "")).upper() in ("SKIP", "NONE", "")
            else data.get("msme_certificate_path"),

        "gst_certificate_path":
            data.get("gst_certificate_path"),

        "declaration_accepted":
            declaration_value == "YES"
            or data.get("declaration_accepted") is True,

        "registration_status":
            "PENDING",

        "erp_sync_status":
            "NOT_SYNCED"
    }