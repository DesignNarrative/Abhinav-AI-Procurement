import re

def extract_categories(principal_business: str, material_types: str) -> list:
    """
    Extract clean category tags from supplier answers to:
      Q2 — What work does your company do?  (principal_business)
      Q3 — What materials do you supply?    (material_types)

    Every word is processed independently so no material or business type is
    ever silently dropped — even when multiple keywords appear in one sentence.
    """

    # Standard normalization: if keyword appears inside a word → use this category name
    norm_map = {
        "cement":      "Cement",
        "steel":       "Steel",
        "electrical":  "Electrical",
        "plumbing":    "Plumbing",
        "hardware":    "Hardware",
        "paint":       "Paint",
        "paints":      "Paint",
        "tiles":       "Tiles",
        "tile":        "Tiles",
        "civil":       "Civil",
        "labour":      "Labour",
        "interior":    "Interior Designing",
        "designing":   "Interior Designing",
        "furniture":   "Furniture",
    }

    # Words to always skip — short connectors and generic business suffixes
    skip_words = {
        "and", "the", "for", "with", "or", "at", "by", "in", "of", "to",
        "a", "an", "is", "on", "are", "our", "we", "all",
        "supply", "supplies", "work", "contractor", "supplier", "department",
    }

    combined = (principal_business or "") + ", " + (material_types or "")

    # First split on hard delimiters (comma, semicolon, newline, pipe, tab)
    chunks = re.split(r"[,;\n\r\t|]", combined)

    categories = set()

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # ── Process every word in this chunk individually ──────────────────
        for word in re.split(r"\s+", chunk):
            word = word.strip().strip(".-/()")
            lower_word = word.lower()

            # Skip empty, very short (≤2 chars), or pure noise words
            if len(lower_word) <= 2 or lower_word in skip_words:
                continue

            # Check all keywords — one word can match multiple (e.g. "steelworks")
            matched = False
            for kw, cat in norm_map.items():
                if kw in lower_word:
                    categories.add(cat)
                    matched = True

            if not matched:
                # Unknown material/type — clean noise suffixes then add title-cased
                clean = re.sub(
                    r"\b(supply|supplies|work|contractor|supplier|department)\b",
                    "",
                    word,
                    flags=re.IGNORECASE,
                ).strip()
                if clean and len(clean) > 2:
                    categories.add(clean.title())

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
            "APPROVED",

        "erp_sync_status":
            "NOT_SYNCED"
    }