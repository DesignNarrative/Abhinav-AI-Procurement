"""
WhatsApp Quotation Service

Handles the complete step-by-step quotation conversation flow on WhatsApp.
Works exactly like supplier registration:
  - One question at a time
  - AI understands typos, mistakes, informal answers
  - Supplier reviews summary before confirming
  - CHANGE [M] [F] to correct any field
  - CONFIRM to submit quotation to DB
"""

import re
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.supplier_quotation_conversation import SupplierQuotationConversation
from app.models.supplier import Supplier
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.services.whatsapp_service import send_text_message

logger = logging.getLogger(__name__)

# ── Field definitions per material ─────────────────────────────────────────
MATERIAL_FIELDS = ["brand", "unit_price", "gst_percent", "total_price", "delivery", "payment_terms"]
FIELD_LABELS = {
    "brand": "Brand",
    "unit_price": "Unit Price",
    "gst_percent": "GST %",
    "total_price": "Total Price (incl GST)",
    "delivery": "Delivery",
    "payment_terms": "Payment Terms",
}

# Intent detection patterns
_QUOTE_PATTERN = re.compile(
    r"^\s*(quot|quote|quotation|rate|rates|send\s*quot|my\s*quot|quoet|quoation|qoute|quaotation|quottation|quatation|kota|cost)\b",
    re.IGNORECASE
)
_CONFIRM_PATTERN = re.compile(
    r"^\s*(confirm|confrim|conferm|konform|yes|ok|done|submit|send|approved|approve|finalize|finalise|cnfrm|cofirm|confirmed)\b",
    re.IGNORECASE
)
_CANCEL_PATTERN = re.compile(
    r"^\s*(cancel|cancle|stop|quit|exit|no|nahi|band\s*karo)\b",
    re.IGNORECASE
)
_HELP_PATTERN = re.compile(
    r"^\s*(help|confused|support|kya\s*karu|kya\s*type|what\s*to\s*type|guide)\b",
    re.IGNORECASE
)
_CHANGE_PATTERN = re.compile(
    r"^\s*(?:change|chnage|chane|cahnge|chang|chenge)\s*(\d+)\s+(\d+)\s*$",
    re.IGNORECASE
)
_SKIP_PATTERN = re.compile(
    r"^\s*(skip|skp|skiip|nahi|dont\s*know|not\s*sure|na|n\/a|na\/)\s*$",
    re.IGNORECASE
)

# Number detection — finds first number in a string
_NUMBER_PATTERN = re.compile(r"[\u20b9rs\.]*\s*([\d,]+(?:\.\d+)?)")


def detect_intent(text: str) -> str:
    """Returns: 'quote', 'confirm', 'cancel', 'help', 'change', 'skip', or 'answer'"""
    t = (text or "").strip()
    if _CANCEL_PATTERN.match(t):
        return "cancel"
    if _CONFIRM_PATTERN.match(t):
        return "confirm"
    if _CHANGE_PATTERN.match(t):
        return "change"
    if _QUOTE_PATTERN.match(t):
        return "quote"
    if _HELP_PATTERN.match(t):
        return "help"
    if _SKIP_PATTERN.match(t):
        return "skip"
    return "answer"


def detect_quote_start(text: str) -> bool:
    """Returns True if supplier typed QUOTE or a clear intent to start quoting."""
    return _QUOTE_PATTERN.match((text or "").strip()) is not None


def extract_number(text: str) -> Optional[str]:
    """Extract first numeric value from text, e.g. '340 rs' -> '340'"""
    text = text.replace(",", "")
    m = _NUMBER_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    return None


def extract_percent(text: str) -> Optional[str]:
    """Extract percentage, e.g. '18%' or '18 percent' -> '18'"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per\s*cent)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return extract_number(text)


# ── Session management ──────────────────────────────────────────────────────

def get_active_session(db: Session, phone: str) -> Optional[SupplierQuotationConversation]:
    """Return active IN_PROGRESS quotation session for this phone number."""
    return db.query(SupplierQuotationConversation).filter(
        SupplierQuotationConversation.phone_number == phone,
        SupplierQuotationConversation.conversation_status == "IN_PROGRESS"
    ).first()


def create_session(db: Session, phone: str, supplier_id: Optional[int]) -> SupplierQuotationConversation:
    """Create a new IN_PROGRESS quotation session."""
    session = SupplierQuotationConversation(
        phone_number=phone,
        supplier_id=supplier_id,
        rfq_id=None,
        conversation_status="IN_PROGRESS",
        current_step="awaiting_rfq_number",
        current_material_index=1,
        collected_data={"rfq_number": None, "materials": []}
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def cancel_session(db: Session, session: SupplierQuotationConversation):
    session.conversation_status = "CANCELLED"
    db.commit()


# ── RFQ resolution ──────────────────────────────────────────────────────────

def resolve_rfq_for_supplier(db: Session, supplier: Supplier, text: str) -> Tuple[Optional[RFQ], str]:
    """
    Smart RFQ linking. Returns (rfq, reason).
    reason: 'found', 'not_invited', 'not_found', 'multiple', 'none'
    """
    if not supplier:
        return None, "none"

    # Get all active RFQs this supplier is invited to
    active_rfq_vendors = db.query(RFQVendor).filter(
        RFQVendor.vendor_id == supplier.id
    ).all()

    active_rfqs = []
    for rv in active_rfq_vendors:
        rfq = db.query(RFQ).filter(
            RFQ.id == rv.rfq_id,
            RFQ.status.notin_(["Closed", "Cancelled"])
        ).first()
        if rfq:
            active_rfqs.append(rfq)

    if not active_rfqs:
        return None, "none"

    # Try to match RFQ number mentioned in text
    text_clean = re.sub(r"[\s\-_/]", "", (text or "").upper())
    for rfq in active_rfqs:
        rfq_clean = re.sub(r"[\s\-_/]", "", rfq.rfq_number.upper())
        # Also try matching just the sequence number at end
        seq = rfq.rfq_number.split("-")[-1].lstrip("0") or "0"
        if rfq_clean in text_clean or (seq and seq in text_clean and len(text_clean) <= 10):
            # Confirm supplier is invited
            return rfq, "found"

    # If only one active RFQ, auto-link
    if len(active_rfqs) == 1:
        return active_rfqs[0], "found"

    # Multiple active RFQs — cannot determine
    return None, "multiple"


def build_rfq_list_message(db: Session, supplier: Supplier) -> str:
    """Build message listing all active RFQs for this supplier to choose from."""
    active_rfq_vendors = db.query(RFQVendor).filter(
        RFQVendor.vendor_id == supplier.id
    ).all()

    lines = ["You have multiple open RFQs. Which one is this quotation for?\n"]
    for i, rv in enumerate(active_rfq_vendors, 1):
        rfq = db.query(RFQ).filter(
            RFQ.id == rv.rfq_id,
            RFQ.status.notin_(["Closed", "Cancelled"])
        ).first()
        if rfq:
            lines.append(f"{i}️⃣ {rfq.rfq_number} — {rfq.project_name or 'Project'}")

    lines.append("\nReply with the RFQ number (e.g. RFQ-2026-033)\nor type the number (1, 2...)")
    return "\n".join(lines)


# ── Question builders ───────────────────────────────────────────────────────

def build_rfq_question() -> str:
    return (
        "What is the RFQ Number?\n"
        "(You can find it in the message we sent you)\n\n"
        "Example: RFQ-2026-033\n"
        "Or type SKIP if you are not sure."
    )


def build_material_intro(mat_data: dict, mat_index: int, total_mats: int) -> str:
    return (
        f"✅ Got it!\n\n"
        f"📦 *Material {mat_index} of {total_mats}: {mat_data['material_name']}*\n"
        f"Qty needed: {mat_data['qty']} {mat_data['unit']}\n\n"
        f"1️⃣ What is your *Brand*?\n"
        f"(Type SKIP if you want to skip this field)"
    )


def build_field_question(field: str, mat_data: dict, field_index: int) -> str:
    unit = mat_data.get("unit", "unit")
    questions = {
        "unit_price": (
            f"2️⃣ *Unit Price per {unit}* (excluding GST)?\n"
            f"Example: 340  or  ₹340\n"
            f"(Type SKIP to skip)"
        ),
        "gst_percent": (
            "3️⃣ *GST %?*\n"
            "Example: 18  or  28%\n"
            "(Type SKIP to skip)"
        ),
        "total_price": (
            f"4️⃣ *Total Price* (including GST) for {mat_data['qty']} {unit}?\n"
            "Example: 43500  or  ₹43,500\n"
            "(Type SKIP — we can calculate it)"
        ),
        "delivery": (
            "5️⃣ *Delivery Timeline?*\n"
            "Example: 3 days  or  within a week\n"
            "(Type SKIP to skip)"
        ),
        "payment_terms": (
            "6️⃣ *Payment Terms?*\n"
            "Example: 30 days credit  or  Advance\n"
            "         50% advance, rest on delivery\n"
            "(Type SKIP to skip)"
        ),
    }
    return questions.get(field, f"Please answer field {field_index}:")


def build_next_material_intro(mat_data: dict, mat_index: int, total_mats: int) -> str:
    return (
        f"📦 *Material {mat_index} of {total_mats}: {mat_data['material_name']}*\n"
        f"Qty needed: {mat_data['qty']} {mat_data['unit']}\n\n"
        f"Can you supply this material?\n"
        f"Type *SKIP* to skip this material entirely,\n"
        f"or answer the first question:\n\n"
        f"1️⃣ What is your *Brand*?\n"
        f"(Type SKIP to skip just this field)"
    )


def build_summary_message(session: SupplierQuotationConversation, db: Session) -> str:
    data = session.collected_data or {}
    rfq = db.query(RFQ).filter(RFQ.id == session.rfq_id).first()
    rfq_number = rfq.rfq_number if rfq else (data.get("rfq_number") or "Unknown RFQ")

    lines = [f"📋 *Quotation Summary — {rfq_number}*", "Please review before submitting.\n"]

    materials = data.get("materials", [])
    for i, mat in enumerate(materials, 1):
        mat_name = mat.get("material_name", "Material")
        qty = mat.get("qty", "")
        unit = mat.get("unit", "")
        lines.append(f"*📦 Material {i}: {mat_name} ({qty} {unit})*")

        if mat.get("skipped"):
            lines.append("Status: ⏭️ Skipped\n")
            continue

        lines.append(f"1️⃣ Brand: {mat.get('brand') or '—'}")
        lines.append(f"2️⃣ Unit Price: {('₹' + str(mat['unit_price'])) if mat.get('unit_price') else '—'}/{unit}")
        lines.append(f"3️⃣ GST: {(str(mat['gst_percent']) + '%') if mat.get('gst_percent') else '—'}")
        lines.append(f"4️⃣ Total Price: {('₹' + str(mat['total_price'])) if mat.get('total_price') else '—'}")
        lines.append(f"5️⃣ Delivery: {mat.get('delivery') or '—'}")
        lines.append(f"6️⃣ Payment: {mat.get('payment_terms') or '—'}")
        lines.append("")

    lines.append("✏️ To change a field, type:")
    lines.append("*CHANGE [Material No.] [Field No.]*")
    lines.append("")
    lines.append("Examples:")
    lines.append("• CHANGE 1 2 → Fix Material 1, Unit Price")
    lines.append("• CHANGE 2 1 → Fix Material 2, Brand")
    lines.append("• CHANGE 1 5 → Fix Material 1, Delivery")
    lines.append("")
    lines.append("✅ Type *CONFIRM* to submit your quotation")

    return "\n".join(lines)


# ── Session save ─────────────────────────────────────────────────────────────

def _generate_quotation_number(db: Session) -> str:
    """Generate next quotation number like QUO-2026-001."""
    from app.models.quotation import Quotation
    year = datetime.now().year
    last = db.query(Quotation).filter(
        Quotation.quotation_number.like(f"QUO-{year}-%")
    ).order_by(Quotation.id.desc()).first()

    if last:
        try:
            seq = int(last.quotation_number.split("-")[-1]) + 1
        except Exception:
            seq = 1
    else:
        seq = 1
    return f"QUO-{year}-{seq:03d}"


def save_confirmed_quotation(db: Session, session: SupplierQuotationConversation) -> Optional[Quotation]:
    """Save completed quotation session to Quotation + QuotationItem tables."""
    try:
        data = session.collected_data or {}
        rfq = db.query(RFQ).filter(RFQ.id == session.rfq_id).first()
        if not rfq:
            logger.error(f"[QUOTATION] RFQ {session.rfq_id} not found during save")
            return None

        quotation_number = _generate_quotation_number(db)

        # Mark any previous quotations from this vendor for this RFQ as not latest
        db.query(Quotation).filter(
            Quotation.rfq_id == rfq.id,
            Quotation.vendor_id == session.supplier_id
        ).update({"is_latest": False})

        quotation = Quotation(
            quotation_number=quotation_number,
            rfq_id=rfq.id,
            vendor_id=session.supplier_id,
            status="Submitted",
            is_latest=True,
            revision_number=1,
            created_by="WHATSAPP",
            date_received=datetime.now().date(),
            creation_source="WHATSAPP",
            grand_total=0.0,
            freight_amount_total=0.0,
            loading_unloading_total=0.0,
        )

        db.add(quotation)
        db.flush()  # get quotation.id

        materials = data.get("materials", [])
        for mat in materials:
            if mat.get("skipped"):
                continue
            rfq_item_id = mat.get("rfq_item_id")
            try:
                unit_price = float(str(mat.get("unit_price", "0")).replace(",", "")) if mat.get("unit_price") else None
                gst_pct = float(str(mat.get("gst_percent", "0")).replace(",", "")) if mat.get("gst_percent") else None
                total_price = float(str(mat.get("total_price", "0")).replace(",", "")) if mat.get("total_price") else None
                qty = float(str(mat.get("qty", "1")).replace(",", "")) if mat.get("qty") else 1
            except (ValueError, TypeError):
                unit_price = None
                gst_pct = None
                total_price = None
                qty = 1

            # Map our collected fields to QuotationItem actual columns
            # basic_rate = unit_price, tax_percent = gst_percent
            # total_item_amount = total_price, final_landed_rate = total_price
            item = QuotationItem(
                quotation_id=quotation.id,
                rfq_item_id=rfq_item_id,
                brand_offered=mat.get("brand"),
                quoted_quantity=qty,
                basic_rate=unit_price or 0.0,
                tax_percent=gst_pct or 0.0,
                total_item_amount=total_price or 0.0,
                final_landed_rate=total_price or 0.0,
                discount_percent=0.0,
                freight_amount=0.0,
                is_quoted=True,
                remarks=f"Delivery: {mat.get('delivery') or 'N/A'} | Payment: {mat.get('payment_terms') or 'N/A'}",
            )
            db.add(item)

        # Compute grand total from items
        all_items_total = sum(
            float(str(mat.get("total_price", 0) or 0).replace(",", ""))
            for mat in materials
            if not mat.get("skipped") and mat.get("total_price")
        )
        if all_items_total:
            quotation.grand_total = all_items_total

        db.commit()
        db.refresh(quotation)

        # Mark session COMPLETED
        session.conversation_status = "COMPLETED"
        db.commit()

        logger.info(f"[QUOTATION] Saved quotation {quotation_number} for RFQ {rfq.rfq_number}")
        return quotation

    except Exception as e:
        db.rollback()
        logger.error(f"[QUOTATION] Error saving quotation: {e}", exc_info=True)
        return None


# ── Process a single step ───────────────────────────────────────────────────

def _get_rfq_items(db: Session, rfq_id: int):
    return db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).order_by(RFQItem.id).all()


def _init_materials_in_data(data: dict, rfq_items) -> dict:
    """Populate materials array in collected_data from RFQ items."""
    data["materials"] = []
    for item in rfq_items:
        data["materials"].append({
            "rfq_item_id": item.id,
            "material_name": item.material_name,
            "qty": str(item.quantity).rstrip("0").rstrip(".") if item.quantity else "?",
            "unit": item.unit or "unit",
            "brand": None,
            "unit_price": None,
            "gst_percent": None,
            "total_price": None,
            "delivery": None,
            "payment_terms": None,
            "skipped": False,
        })
    return data


def process_quotation_step(db: Session, session: SupplierQuotationConversation,
                            message_text: str, supplier: Supplier) -> str:
    """
    Core state machine. Given current session state and supplier message,
    returns the next reply string (to be sent via WhatsApp).
    """
    text = (message_text or "").strip()
    intent = detect_intent(text)
    data = session.collected_data or {}
    if not isinstance(data, dict):
        data = {}

    # ── CANCEL ──────────────────────────────────────────────────────────────
    if intent == "cancel":
        cancel_session(db, session)
        return (
            "Your quotation session has been cancelled.\n\n"
            "You can start again anytime by typing *QUOTE*."
        )

    # ── HELP ────────────────────────────────────────────────────────────────
    if intent == "help":
        step = session.current_step
        if step == "awaiting_rfq_number":
            return (
                "📋 Please type the RFQ number from the message we sent you.\n"
                "Example: RFQ-2026-033\n\n"
                "Type CANCEL to stop."
            )
        elif step == "summary":
            return (
                "📋 You are at the review step.\n\n"
                "• Type *CONFIRM* to submit\n"
                "• Type *CHANGE 1 2* to fix Material 1, Field 2\n"
                "• Type *CANCEL* to cancel\n\n"
                "Fields: 1=Brand, 2=Unit Price, 3=GST%, 4=Total Price, 5=Delivery, 6=Payment"
            )
        else:
            return (
                "📋 Just reply with your answer for the current question.\n"
                "Type SKIP to skip any field.\n"
                "Type CANCEL to stop the quotation."
            )

    step = session.current_step

    # ── STEP: awaiting_rfq_number ────────────────────────────────────────────
    if step == "awaiting_rfq_number":
        if intent == "skip":
            # Try to auto-resolve if only one active RFQ
            rfq, reason = resolve_rfq_for_supplier(db, supplier, "")
            if reason == "found" and rfq:
                session.rfq_id = rfq.id
                data["rfq_number"] = rfq.rfq_number
                rfq_items = _get_rfq_items(db, rfq.id)
                data = _init_materials_in_data(data, rfq_items)
                session.collected_data = data
                session.current_step = "m1_brand"
                session.current_material_index = 1
                db.commit()
                return build_material_intro(data["materials"][0], 1, len(rfq_items))
            elif reason == "multiple":
                return build_rfq_list_message(db, supplier)
            else:
                return (
                    "❌ Could not find any open RFQ for you.\n"
                    "Please check the RFQ number and try again.\n"
                    "Or type HELP and your Purchase Manager will assist."
                )

        # Try to match RFQ number from text
        rfq, reason = resolve_rfq_for_supplier(db, supplier, text)

        if reason == "found" and rfq:
            session.rfq_id = rfq.id
            data["rfq_number"] = rfq.rfq_number
            rfq_items = _get_rfq_items(db, rfq.id)
            data = _init_materials_in_data(data, rfq_items)
            session.collected_data = data
            session.current_step = "m1_brand"
            session.current_material_index = 1
            db.commit()
            return build_material_intro(data["materials"][0], 1, len(rfq_items))

        elif reason == "multiple":
            return build_rfq_list_message(db, supplier)

        elif reason == "not_invited":
            return (
                "❌ You are not invited to that RFQ.\n"
                "Please contact your Purchase Manager for assistance."
            )
        else:
            return (
                "❌ Could not find that RFQ number.\n"
                "Please check the message we sent you and try again.\n\n"
                "Example: RFQ-2026-033\n"
                "Or type HELP."
            )

    # ── STEPS: m{i}_{field} ─────────────────────────────────────────────────
    materials = data.get("materials", [])
    total_mats = len(materials)
    mat_idx = session.current_material_index - 1  # 0-based index

    if mat_idx < 0 or mat_idx >= total_mats:
        # Fallback — move to summary
        session.current_step = "summary"
        db.commit()
        return build_summary_message(session, db)

    mat = materials[mat_idx]

    # Parse current field from step name like "m2_brand" -> field="brand"
    field = None
    for f in MATERIAL_FIELDS:
        if step == f"m{session.current_material_index}_{f}":
            field = f
            break

    if field is None and step != "summary":
        # Unknown step — move to summary
        session.current_step = "summary"
        db.commit()
        return build_summary_message(session, db)

    # ── SUMMARY step ────────────────────────────────────────────────────────
    if step == "summary":
        if intent == "confirm":
            quotation = save_confirmed_quotation(db, session)
            if quotation:
                return (
                    "🎉 *Quotation Submitted Successfully!*\n\n"
                    f"RFQ: {data.get('rfq_number', '')}\n"
                    "Your rates have been recorded.\n"
                    "We will review and get back to you.\n\n"
                    "Thank you! 🙏\n"
                    "*— Abhinav Group Purchase Team*"
                )
            else:
                return (
                    "❌ There was an error saving your quotation.\n"
                    "Please type CONFIRM to try again, or contact your Purchase Manager."
                )

        elif intent == "change":
            m = _CHANGE_PATTERN.match(text)
            if m:
                mat_num = int(m.group(1))
                field_num = int(m.group(2))

                if 1 <= mat_num <= total_mats and 1 <= field_num <= 6:
                    target_field = MATERIAL_FIELDS[field_num - 1]
                    target_mat = materials[mat_num - 1]
                    current_val = target_mat.get(target_field) or "—"

                    session.current_step = f"m{mat_num}_{target_field}"
                    session.current_material_index = mat_num
                    db.commit()

                    return (
                        f"You selected:\n"
                        f"Material {mat_num} — {target_mat.get('material_name', '')}\n"
                        f"{field_num}️⃣ {FIELD_LABELS[target_field]}: {current_val}\n\n"
                        f"What should it be?\n"
                        f"(Type the new value, or SKIP to clear it)"
                    )
                else:
                    return (
                        "Please use: CHANGE [Material No.] [Field No.]\n"
                        "Example: CHANGE 1 2\n\n"
                        "Fields: 1=Brand, 2=Unit Price, 3=GST%, 4=Total Price, 5=Delivery, 6=Payment"
                    )
            # Try to detect a plain number (e.g. supplier types "2" thinking it means CHANGE 2)
            plain_num = re.match(r"^\s*(\d+)\s*$", text)
            if plain_num:
                return (
                    "To change a field, type: CHANGE [Material No.] [Field No.]\n"
                    "Example: CHANGE 1 2 to fix Material 1, Unit Price\n\n"
                    "Or type CONFIRM to submit."
                )
            return build_summary_message(session, db)

        else:
            # Unrecognized — re-show summary
            return build_summary_message(session, db)

    # ── COLLECTING FIELD ────────────────────────────────────────────────────

    # If this is a material start (brand field) and supplier says SKIP — skip entire material
    if field == "brand" and intent == "skip":
        # Check if it is the WHOLE material skip (only at intro)
        materials[mat_idx]["skipped"] = True
        session.collected_data = data
        # Move to next material or summary
        return _advance_after_field(db, session, data, mat_idx, total_mats, skip_material=True)

    if intent == "skip":
        # Skip just this field
        materials[mat_idx][field] = None
        session.collected_data = data
        return _advance_after_field(db, session, data, mat_idx, total_mats)

    # Parse and save the answer
    saved_value = _parse_field_answer(field, text, mat)
    materials[mat_idx][field] = saved_value
    session.collected_data = data
    db.commit()

    return _advance_after_field(db, session, data, mat_idx, total_mats)


def _parse_field_answer(field: str, text: str, mat: dict) -> str:
    """Parse raw text answer into a clean value for the given field."""
    text = text.strip()

    if field == "brand":
        # Accept as-is (clean up punctuation slightly)
        return re.sub(r"^[-:*\s]+", "", text).strip()

    elif field == "unit_price":
        num = extract_number(text)
        return num or text

    elif field == "gst_percent":
        pct = extract_percent(text)
        return pct or text

    elif field == "total_price":
        num = extract_number(text)
        return num or text

    elif field == "delivery":
        return text

    elif field == "payment_terms":
        return text

    return text


def _advance_after_field(db: Session, session: SupplierQuotationConversation,
                          data: dict, mat_idx: int, total_mats: int,
                          skip_material: bool = False) -> str:
    """Move session to the next step after answering/skipping a field."""
    materials = data.get("materials", [])

    if skip_material:
        # Move to next material
        next_mat_idx = mat_idx + 1
        if next_mat_idx >= total_mats:
            session.current_step = "summary"
            db.commit()
            return build_summary_message(session, db)
        else:
            session.current_material_index = next_mat_idx + 1
            session.current_step = f"m{next_mat_idx + 1}_brand"
            db.commit()
            return build_next_material_intro(materials[next_mat_idx], next_mat_idx + 1, total_mats)

    # Figure out which field we just answered
    current_field = None
    step = session.current_step
    for f in MATERIAL_FIELDS:
        if step == f"m{session.current_material_index}_{f}":
            current_field = f
            break

    if current_field is None:
        session.current_step = "summary"
        db.commit()
        return build_summary_message(session, db)

    field_idx = MATERIAL_FIELDS.index(current_field)
    next_field_idx = field_idx + 1

    if next_field_idx < len(MATERIAL_FIELDS):
        # Move to next field for same material
        next_field = MATERIAL_FIELDS[next_field_idx]
        session.current_step = f"m{session.current_material_index}_{next_field}"
        db.commit()
        return build_field_question(next_field, materials[mat_idx], next_field_idx + 1)
    else:
        # Done with this material — move to next material or summary
        next_mat_idx = mat_idx + 1
        if next_mat_idx >= total_mats:
            session.current_step = "summary"
            db.commit()
            return build_summary_message(session, db)
        else:
            session.current_material_index = next_mat_idx + 1
            session.current_step = f"m{next_mat_idx + 1}_brand"
            db.commit()
            return build_next_material_intro(materials[next_mat_idx], next_mat_idx + 1, total_mats)


# ── Entry point ─────────────────────────────────────────────────────────────

def handle_inbound_quotation_message(db: Session, supplier: Supplier,
                                      sender_phone: str, message_text: str) -> Optional[str]:
    """
    Main entry point called from the WhatsApp webhook.
    Returns the reply string if bot should respond, or None if silent.

    Handles:
      1. Active quotation session in progress → continue that session
      2. Supplier types QUOTE / QUOTATION → start new session
      3. Otherwise → return None (stay silent, PM handles in inbox)
    """
    text = (message_text or "").strip()

    # Check for active session
    session = get_active_session(db, sender_phone)

    if session:
        # Continue existing session
        return process_quotation_step(db, session, text, supplier)

    # Detect QUOTE intent — start new session
    if detect_quote_start(text):
        # Check if supplier is APPROVED
        if not supplier or supplier.registration_status != "APPROVED":
            return None  # Not approved — registration flow handles this

        session = create_session(db, sender_phone, supplier.id)

        # Try to auto-link if only one active RFQ
        rfq, reason = resolve_rfq_for_supplier(db, supplier, text)

        if reason == "found" and rfq:
            rfq_items = _get_rfq_items(db, rfq.id)
            if not rfq_items:
                cancel_session(db, session)
                return (
                    "❌ No materials found in that RFQ.\n"
                    "Please contact your Purchase Manager."
                )
            data = session.collected_data or {}
            data["rfq_number"] = rfq.rfq_number
            session.rfq_id = rfq.id
            data = _init_materials_in_data(data, rfq_items)
            session.collected_data = data
            session.current_step = "m1_brand"
            session.current_material_index = 1
            db.commit()

            return (
                f"✅ We found your open RFQ: *{rfq.rfq_number}*\n"
                f"Let's proceed with your quotation.\n\n"
            ) + build_material_intro(data["materials"][0], 1, len(rfq_items))

        elif reason == "multiple":
            # Keep session but ask for RFQ number
            db.commit()
            return (
                "📝 *Starting Quotation*\n\n" +
                build_rfq_question()
            )

        elif reason == "none":
            cancel_session(db, session)
            return (
                "❌ You don't have any open RFQs at the moment.\n"
                "Please contact your Purchase Manager."
            )
        else:
            # Keep session, ask for RFQ number
            db.commit()
            return (
                "📝 *Starting Quotation*\n\n" +
                build_rfq_question()
            )

    # Not a quotation intent — stay silent
    return None


