import re

def extract_categories(principal_business: str, material_types: str) -> list:
    """Combine and process Q2 and Q3 responses to dynamically extract clean tags/categories."""
    combined = f"{principal_business or ''}, {material_types or ''}"
    parts = re.split(r'[,;\n\r\t|]', combined)

    # Standard normalization mapping
    norm_map = {
        "cement": "Cement",
        "steel": "Steel",
        "electrical": "Electrical",
        "plumbing": "Plumbing",
        "hardware": "Hardware",
        "paint": "Paint",
        "paints": "Paint",
        "tiles": "Tiles",
        "civil": "Civil",
        "labour": "Labour",
        "interior": "Interior Designing",
        "designing": "Interior Designing",
        "furniture": "Furniture",
    }

    categories = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue

        lower_part = part.lower()
        matched = False
        for kw, cat in norm_map.items():
            if kw in lower_part:
                categories.add(cat)
                matched = True

        if not matched:
            # Clean up suffix noise
            clean_part = re.sub(
                r'\b(supply|supplies|work|contractor|supplier|department)\b', 
                '', 
                lower_part, 
                flags=re.IGNORECASE
            ).strip()
            if clean_part and len(clean_part) > 2:
                categories.add(clean_part.title())
            elif part and len(part) > 2:
                categories.add(part.title())

    return sorted(list(categories))


def map_conversation_to_supplier(data: dict):

    is_msme_value = str(
        data.get("is_msme", "")
    ).upper()

    declaration_value = str(
        data.get("declaration_accepted", "")
    ).upper()

    # Dynamic extraction of categories from principal_business (Q2) and material_types (Q3)
    p_biz = data.get("principal_business")
    m_types = data.get("material_types")
    extracted_cats = extract_categories(p_biz, m_types)

    return {

        "company_name":
            data.get("company_name"),

        "principal_business":
            p_biz,

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

        "supplier_category":
            ", ".join(extracted_cats) if extracted_cats else None,

        "material_types":
            m_types,

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