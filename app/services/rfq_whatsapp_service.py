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
    purchase_team_number: Optional[str] = None,
) -> str:
    """
    Generates a short, human-sounding WhatsApp RFQ message.
    """
    lines = []

    lines.append("Hello! 👋")
    lines.append("")

    lines.append(f"📋 *RFQ No.: {rfq_number}*")
    lines.append("")

    lines.append("We are *Abhinav Group* (Real estate builders & construction company in Pune).")
    lines.append("We are looking for rates/availability of these materials for our project:")
    lines.append("")

    lines.append("*Materials Required:*")
    for item in items:
        brand_info = f" (Brand: {item['brand_required']})" if item.get("brand_required") else ""
        lines.append(f"📦 {item.get('material_name', 'N/A')} — {item.get('quantity', '-')} {item.get('unit', '')}{brand_info}")
        
        # Dynamic fields (e.g. specifications)
        dynamic = item.get("dynamic_fields") or {}
        for key, value in dynamic.items():
            if value is not None and str(value).strip() not in ("", "None"):
                lines.append(f"  • {_label(key)}: {value}")
        
        if item.get("remarks"):
            lines.append(f"  • Purpose: {item['remarks']}")

    lines.append("")
    lines.append(f"📍 Delivery: {delivery_location}")
    
    if required_date:
        lines.append(f"📅 Required By: {required_date}")
        
    if purpose:
        lines.append(f"🎯 Purpose: {purpose}")
    
    if payment_terms:
        lines.append(f"💳 Payment Terms: {payment_terms}")

    # Display Send Options (Site Contact fields) separately if filled
    if deadline and deadline.strip():
        lines.append(f"📅 Quotation Deadline: {deadline.strip()}")
    if contact_person and contact_person.strip():
        lines.append(f"👤 Site Contact Person: {contact_person.strip()}")
    if contact_number and contact_number.strip():
        lines.append(f"📞 Site Contact Number: {contact_number.strip()}")
        
    lines.append("")
    lines.append("Please reply in this chat with your best rate (mention GST separately) and delivery timeline.")
    lines.append("")

    # Determine final purchase team number
    final_purchase_number = "7219550051"
    if purchase_team_number and purchase_team_number.strip():
        final_purchase_number = purchase_team_number.strip()

    lines.append("Thanks,")
    lines.append("Abhinav Group — Purchase Team")
    lines.append(f"📞{final_purchase_number}")

    return "\n".join(lines)


def generate_quotation_trigger_message(rfq_number: str) -> str:
    """
    Short trigger message sent right after the RFQ message.
    Tells the supplier how to start the quotation process.
    """
    return (
        f"📝 Got the RFQ?\n\n"
        f"To send your quotation for *{rfq_number}*, type:\n"
        f"*Quote*\n\n"
        f"We will guide you step by step. 👍"
    )


def send_award_winner_message(supplier, rfq, po=None) -> bool:
    """
    Send congratulatory WhatsApp message to the winning supplier.
    Returns True if sent successfully.
    """
    from app.services.whatsapp_service import send_text_message
    phone = supplier.whatsapp_number
    if not phone:
        return False
    if not phone.startswith("+"):
        phone = f"91{phone}" if len(phone) == 10 else phone

    rfq_number = rfq.rfq_number if rfq else "this RFQ"
    project_name = (rfq.project_name or "your project") if rfq else "your project"
    supplier_name = supplier.company_name or "Supplier"

    message = (
        f"🎉 *Congratulations, {supplier_name}!*\n\n"
        f"We are delighted to inform you that your quotation for\n"
        f"*{rfq_number} — {project_name}*\n"
        f"has been selected by *Abhinav Group*! 🏆\n\n"
        f"Your pricing, quality commitment, and delivery terms\n"
        f"impressed us the most.\n\n"
        f"📋 *What's Next:*\n"
        f"Your Purchase Order is being prepared and will be\n"
        f"shared with you shortly. Please keep the materials\n"
        f"ready as per your quoted delivery timeline.\n\n"
        f"We truly value your trust and partnership.\n"
        f"Looking forward to a successful delivery! 💼🤝\n\n"
        f"Thank you,\n"
        f"*Abhinav Group — Purchase Department*"
    )

    try:
        send_text_message(phone, message)
        return True
    except Exception as e:
        print(f"[AWARD] Failed to send winner message to {phone}: {e}")
        return False


def send_award_consolation_message(supplier, rfq) -> bool:
    """
    Send respectful not-selected WhatsApp message to non-winning suppliers.
    Returns True if sent successfully.
    """
    from app.services.whatsapp_service import send_text_message
    phone = supplier.whatsapp_number
    if not phone:
        return False
    if not phone.startswith("+"):
        phone = f"91{phone}" if len(phone) == 10 else phone

    rfq_number = rfq.rfq_number if rfq else "this RFQ"
    project_name = (rfq.project_name or "this project") if rfq else "this project"
    supplier_name = supplier.company_name or "Supplier"

    message = (
        f"🙏 *Thank You — {supplier_name}*\n\n"
        f"We sincerely appreciate you taking the time to send\n"
        f"your quotation for *{rfq_number} — {project_name}*.\n\n"
        f"After careful review of all quotations received,\n"
        f"we have finalized this order with another supplier.\n"
        f"The decision was based on overall pricing, delivery\n"
        f"terms, and project-specific requirements.\n\n"
        f"Please do not be discouraged — this is not a\n"
        f"reflection of your quality or service. We look\n"
        f"forward to working with you on our upcoming\n"
        f"requirements, and you will continue to receive\n"
        f"our future RFQs. 🤝\n\n"
        f"Thank you once again for your response and support.\n"
        f"We truly value your partnership!\n\n"
        f"Warm regards,\n"
        f"*Abhinav Group — Purchase Department*"
    )

    try:
        send_text_message(phone, message)
        return True
    except Exception as e:
        print(f"[AWARD] Failed to send consolation message to {phone}: {e}")
        return False
