"""
RFQ WhatsApp Message Generator.

This module is completely dynamic. It does NOT have any hardcoded material types.
The WhatsApp message is assembled intelligently based on whatever data is provided:
  - If a field has a value, it is included.
  - If a field is empty or None, it is skipped entirely.
  - dynamic_fields (JSONB) keys are converted to readable labels automatically.
  - This works for ANY material type, anywhere in the world, now or in the future.
"""

from typing import List, Optional, Dict, Any


def _label(key: str) -> str:
    """Convert a snake_case or camelCase key to a human-readable label."""
    import re
    # Insert spaces before caps for camelCase, then replace underscores
    key = re.sub(r'([A-Z])', r' \1', key)
    key = key.replace("_", " ").strip()
    return key.title()


def generate_rfq_whatsapp_message(
    rfq_number: str,
    project_name: str,
    site_name: str,
    delivery_location: str,
    payment_terms: Optional[str],
    items: List[Dict[str, Any]],
    deadline: Optional[str] = None,
    contact_person: Optional[str] = None,
    contact_number: Optional[str] = None,
    priority: Optional[str] = None,
    required_date: Optional[str] = None,
    purpose: Optional[str] = None,
) -> str:
    """
    Generates a professional, intelligent WhatsApp RFQ message.

    Rules:
    1. Only includes fields that have a value — no empty lines.
    2. Works for any material type worldwide — no hardcoded categories.
    3. The dynamic_fields dict keys are auto-converted to readable labels.
    4. Multi-item RFQs are properly numbered.
    """

    lines = []

    # ── Header ──
    lines.append(f"*REQUEST FOR QUOTATION*")
    lines.append(f"*RFQ No:* {rfq_number}")
    lines.append("")

    # ── Project Info ──
    lines.append(f"*Project:* {project_name}")
    if site_name:
        lines.append(f"*Site:* {site_name}")
    lines.append(f"*Delivery Location:* {delivery_location}")
    if priority:
        lines.append(f"*Priority:* {priority}")
    if required_date:
        lines.append(f"*Required By:* {required_date}")
    if purpose:
        lines.append(f"*Purpose:* {purpose}")
    lines.append("")

    # ── Items ──
    lines.append("*Materials Required:*")
    lines.append("-" * 32)

    for i, item in enumerate(items, start=1):
        lines.append(f"*Item {i}: {item.get('material_name', 'N/A')}*")
        lines.append(f"  • Category: {item.get('material_category', '-')}")
        lines.append(f"  • Quantity: {item.get('quantity', '-')} {item.get('unit', '')}")

        if item.get("brand_required"):
            lines.append(f"  • Brand: {item['brand_required']}")

        # Dynamic fields — works for any material type
        dynamic = item.get("dynamic_fields") or {}
        for key, value in dynamic.items():
            if value is not None and str(value).strip() not in ("", "None"):
                lines.append(f"  • {_label(key)}: {value}")

        if item.get("remarks"):
            lines.append(f"  • Note: {item['remarks']}")

        lines.append("")

    lines.append("-" * 32)

    # ── Terms ──
    terms_added = False
    if payment_terms:
        lines.append(f"*Payment Terms:* {payment_terms}")
        terms_added = True
    if terms_added:
        lines.append("")

    # ── Contact ──
    if contact_person or contact_number:
        lines.append("*Site Contact:*")
        if contact_person:
            lines.append(f"  {contact_person}")
        if contact_number:
            lines.append(f"  Tel: {contact_number}")
        lines.append("")

    # ── Deadline ──
    if deadline:
        lines.append(f"*Quotation Deadline:* {deadline}")
        lines.append("")

    # ── Footer ──
    lines.append("Please share your best rate.")
    lines.append("Mention GST separately.")
    lines.append("Include transport and loading/unloading details.")
    lines.append("")
    lines.append("*Abhinav Group — Purchase Department*")

    return "\n".join(lines)
