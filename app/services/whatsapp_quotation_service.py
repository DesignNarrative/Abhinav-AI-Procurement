"""
WhatsApp Quotation Service

5-question flow per material:
  1. Brand / Make
  2. Total Price  (all-inclusive: GST + freight + loading/unloading + ALL charges)
  3. Delivery Timeline
  4. Payment Terms
  5. Remarks / Special Conditions

For 2+ materials: asks Combined Grand Total after all materials are done.

AI understands any format suppliers type:
  - Price: 43.5k, 1.5 lakh, Rs 43500, 43,500/-, hajar, etc.
  - Delivery: aaj, kal, 3 din, asap, ready stock, ek hafta, etc.
  - Payment: pehle paisa, cod, 30 din credit, rtgs, etc.
  - Commands: any spelling/typo of CONFIRM, CANCEL, CHANGE, SKIP
  - CHANGE in any format: "1 2", "1-2", "1,2", "CHANGE 1 2", typos of CHANGE
"""

import re
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

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
MATERIAL_FIELDS = ["brand", "total_price", "delivery", "payment_terms", "remarks_note"]
FIELD_LABELS = {
    "brand":         "Brand / Make",
    "total_price":   "Total Price (all-inclusive)",
    "delivery":      "Delivery Timeline",
    "payment_terms": "Payment Terms",
    "remarks_note":  "Remarks / Special Conditions",
}

# ── Intent detection patterns ────────────────────────────────────────────────
_QUOTE_PATTERN = re.compile(
    r"^\s*(quot|quote|quotation|rate|rates|send\s*quot|my\s*quot|quoet|quoation|qoute|"
    r"quaotation|quottation|quatation|kota|cost)\b",
    re.IGNORECASE
)
_CONFIRM_PATTERN = re.compile(
    r"^\s*(confirm|confrim|conferm|konform|yes|ok|okay|done|submit|send|approved|approve|"
    r"finalize|finalise|cnfirm|cofirm|confirmed|cofirmed|comfirm|confirmn|confimr|cfm|"
    r"submitt|haan|bhejo|send\s*kar|final|ho\s*gaya)\b",
    re.IGNORECASE
)
_CANCEL_PATTERN = re.compile(
    r"^\s*(cancel|cancle|stop|quit|exit|no|nahi|band\s*karo|canncel|canell|cancell|"
    r"mat\s*bhejo|mat\s*send|rok\s*do|nai|nah)\b",
    re.IGNORECASE
)
_HELP_PATTERN = re.compile(
    r"^\s*(help|confused|support|kya\s*karu|kya\s*type|what\s*to\s*type|guide)\b",
    re.IGNORECASE
)
# CHANGE: requires keyword; handles "change 1 2", "change 1-2", "change 1,2", typos
_CHANGE_PATTERN = re.compile(
    r"^\s*(?:change|chnage|chane|cahnge|chang|chenge|chaneg)\s+(\d+)\s*[-,]?\s*(\d+)\s*$",
    re.IGNORECASE
)
_SKIP_PATTERN = re.compile(
    r"^\s*(skip|skp|skiip|nahi|dont\s*know|not\s*sure|na|n\/a|na\/|nai\s*pata|"
    r"pata\s*nahi|nhi|cant\s*say|cannot\s*say|will\s*tell\s*later|tbd|will\s*confirm)\s*$",
    re.IGNORECASE
)

# Two-number pattern: "X Y", "X-Y", "X,Y" at summary => treat as CHANGE X Y
_TWO_NUM_PATTERN = re.compile(r"^\s*(\d+)\s*[-,\s]\s*(\d+)\s*$")

# Number detection
_NUMBER_PATTERN = re.compile(r"[\u20b9rs\.]*\s*([\d,]+(?:\.\d+)?)")


# ── Intent detection ─────────────────────────────────────────────────────────

def detect_intent(text: str) -> str:
    """Returns: 'quote' / 'confirm' / 'cancel' / 'help' / 'change' / 'skip' / 'answer'"""
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


# ── Smart price parser ───────────────────────────────────────────────────────

def _parse_price_smart(text: str) -> Optional[str]:
    """
    Parse any price format into a clean integer string.
    Handles: 43500, Rs 43500, 43,500, 43500/-, 43.5k, 1.5 lakh/lac/L,
             1cr/crore, 45 hajar/hazar, "price is 43500", "can give at 43500" etc.
    Returns string like "43500" or None if no number found.
    """
    if not text:
        return None
    t = text.strip().lower()
    t = re.sub(r"\u20b9", "", t)
    t = re.sub(r"\brs\.?\b", "", t)
    t = re.sub(r"/-+$", "", t).strip()

    # crore/cr = 10,000,000
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:crore|crores|cr)\b", t)
    if m:
        try:
            return str(int(float(m.group(1).replace(",", "")) * 10_000_000))
        except Exception:
            pass

    # lakh/lac/L = 100,000
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs|l\b)", t)
    if m:
        try:
            return str(int(float(m.group(1).replace(",", "")) * 100_000))
        except Exception:
            pass

    # hajar/hazar/thousand = 1,000
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:hajar|hazar|thousand)\b", t)
    if m:
        try:
            return str(int(float(m.group(1).replace(",", "")) * 1_000))
        except Exception:
            pass

    # k = 1,000
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*k\b", t)
    if m:
        try:
            return str(int(float(m.group(1).replace(",", "")) * 1_000))
        except Exception:
            pass

    # Plain number (with commas, optional trailing / or -)
    t_clean = re.sub(r"[/\-]+$", "", t).strip()
    m = re.search(r"([\d,]+(?:\.\d+)?)", t_clean)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            if val > 0:
                return str(int(val)) if val == int(val) else str(round(val, 2))
        except Exception:
            pass

    return None


# ── Smart delivery normalizer ────────────────────────────────────────────────

def _normalize_delivery(text: str) -> str:
    """
    Normalize delivery timeline text to clean English.
    Accepts Hindi, abbreviations, informal language.
    Returns normalized text, or original if no normalization applies.
    """
    if not text:
        return text
    t = text.strip().lower()

    if re.search(r"\b(aaj|aj|today|same\s*day|turant|abhi|immediately|immediate|asap|"
                 r"right\s*away|jaldi|instant)\b", t):
        return "Immediate / Same day"

    if re.search(r"\b(kal|tomorrow|next\s*day|agle\s*din|doosre\s*din)\b", t):
        return "Next day"

    if re.search(r"\b(ready|in\s*stock|stock\s*me|stock\s*mein|stock\s*hai|"
                 r"available|ex\s*stock)\b", t):
        return "Ready stock / Immediate"

    # Range: "2-3 days"
    m = re.search(r"(\d+)\s*[-to]+\s*(\d+)\s*(?:days?|din|working\s*days?|d\b)", t)
    if m:
        suffix = " working days" if "working" in t else " days"
        return f"{m.group(1)}-{m.group(2)}{suffix}"

    # X days/din/d
    m = re.search(r"(\d+)\s*(?:days?|din\b|d\b|working\s*days?|business\s*days?)", t)
    if m:
        n = int(m.group(1))
        if "working" in t or "business" in t:
            return f"{n} working day{'s' if n > 1 else ''}"
        return f"{n} day{'s' if n > 1 else ''}"

    # Within X days/week
    m = re.search(r"within\s*(\d+)\s*(?:days?|din|week|hafta)", t)
    if m:
        unit = "week" if re.search(r"(week|hafta)", t) else "days"
        return f"Within {m.group(1)} {unit}"

    # X weeks
    m = re.search(r"(\d+)\s*(?:weeks?|hafta|hafte)", t)
    if m:
        n = int(m.group(1))
        return f"{n} week{'s' if n > 1 else ''}"

    # X months
    m = re.search(r"(\d+)\s*(?:months?|mahine?|maas)", t)
    if m:
        n = int(m.group(1))
        return f"{n} month{'s' if n > 1 else ''}"

    # Hindi number words
    hindi_nums = {"ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4,
                  "paanch": 5, "panch": 5, "chhe": 6, "saat": 7, "das": 10}
    for word, num in hindi_nums.items():
        if re.search(rf"\b{word}\b", t):
            if re.search(r"\b(din|day)", t):
                return f"{num} day{'s' if num > 1 else ''}"
            if re.search(r"\b(hafta|hafte|week)", t):
                return f"{num} week{'s' if num > 1 else ''}"

    if re.search(r"\b(after\s*po|after\s*order|po\s*ke\s*baad|after\s*confirmation)\b", t):
        return "After PO confirmation"

    return text.strip()


# ── Smart payment normalizer ─────────────────────────────────────────────────

def _normalize_payment(text: str) -> str:
    """
    Normalize payment terms to clean English.
    Handles Hindi, abbreviations, informal language.
    """
    if not text:
        return text
    t = text.strip().lower()

    if re.search(r"\b(pehle\s*paisa|pahle\s*payment|pehle\s*payment|100\s*%?\s*advance|"
                 r"full\s*advance|advance\s*full|poora\s*advance|pura\s*advance)\b", t):
        return "100% Advance"

    m = re.search(r"(\d+)\s*%?\s*(?:advance|pahle|pehle).{0,30}?(?:rest|baki|remaining|delivery|baaki)", t)
    if m:
        pct = int(m.group(1))
        return f"{pct}% advance, {100 - pct}% on delivery"

    if re.search(r"\b(against\s*delivery|delivery\s*ke\s*saath|delivery\s*pe|"
                 r"cod\b|cash\s*on\s*delivery|delivery\s*par)\b", t):
        return "Against delivery (COD)"

    m = re.search(r"(\d+)\s*(?:days?|din)?\s*credit", t)
    if not m:
        m = re.search(r"credit\s*(?:of\s*)?(\d+)\s*(?:days?|din)?", t)
    if not m:
        m = re.search(r"net\s*(\d+)", t)
    if m:
        return f"{m.group(1)} days credit"

    if re.search(r"\b(immediate|immediately|turant)\b", t):
        return "Immediate payment"

    mode_m = re.search(r"\b(rtgs|neft|upi|cheque|check|bank\s*transfer|dd\b|demand\s*draft)\b", t)
    if mode_m:
        mode = mode_m.group(1).upper()
        days_m = re.search(r"(\d+)\s*(?:days?|din)", t)
        if days_m:
            return f"{days_m.group(1)} days credit via {mode}"
        return f"Payment via {mode}"

    if re.match(r"^\s*advance\s*$", t):
        return "Advance"

    return text.strip()


# ── Session management ───────────────────────────────────────────────────────

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
        collected_data={"rfq_number": None, "materials": [], "combined_total": None}
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def cancel_session(db: Session, session: SupplierQuotationConversation):
    session.conversation_status = "CANCELLED"
    db.commit()


# ── RFQ resolution ───────────────────────────────────────────────────────────

def resolve_rfq_for_supplier(db: Session, supplier: Supplier, text: str) -> Tuple[Optional[RFQ], str]:
    """Smart RFQ linking. Returns (rfq, reason)."""
    if not supplier:
        return None, "none"
    active_rfq_vendors = db.query(RFQVendor).filter(RFQVendor.vendor_id == supplier.id).all()
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
    text_clean = re.sub(r"[\s\-_/]", "", (text or "").upper())
    for rfq in active_rfqs:
        rfq_clean = re.sub(r"[\s\-_/]", "", rfq.rfq_number.upper())
        seq = rfq.rfq_number.split("-")[-1].lstrip("0") or "0"
        if rfq_clean in text_clean or (seq and seq in text_clean and len(text_clean) <= 10):
            return rfq, "found"
    if len(active_rfqs) == 1:
        return active_rfqs[0], "found"
    return None, "multiple"


def build_rfq_list_message(db: Session, supplier: Supplier) -> str:
    """Build message listing all active RFQs for this supplier to choose from."""
    active_rfq_vendors = db.query(RFQVendor).filter(RFQVendor.vendor_id == supplier.id).all()
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


# ── Question builders ────────────────────────────────────────────────────────

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
        f"1️⃣ *Brand / Make?*\n"
        f"(What brand of material are you providing?)\n"
        f"Example: JSW, UltraTech, Havells\n"
        f"(Type SKIP if not applicable)"
    )


def build_field_question(field: str, mat_data: dict, field_index: int) -> str:
    unit = mat_data.get("unit", "unit")
    qty = mat_data.get("qty", "")
    questions = {
        "total_price": (
            f"2️⃣ *Your Best Total Price for {qty} {unit}?*\n"
            f"📌 Include EVERYTHING in this price:\n"
            f"   • GST\n"
            f"   • Freight & Transport\n"
            f"   • Loading & Unloading\n"
            f"   • Any other charges\n\n"
            f"This is the final amount we pay — no hidden charges.\n"
            f"Example: 43500  or  ₹43,500  or  43.5k\n"
            f"(Type SKIP if you cannot provide a total right now)"
        ),
        "delivery": (
            "3️⃣ *Delivery Timeline?*\n"
            "When can you deliver after order confirmation?\n"
            "Example: 3 days  or  Within 1 week  or  Immediate\n"
            "(Type SKIP if unsure)"
        ),
        "payment_terms": (
            "4️⃣ *Payment Terms?*\n"
            "Example: 30 days credit  or  Advance\n"
            "         50% advance, rest on delivery\n"
            "(Type SKIP to skip)"
        ),
        "remarks_note": (
            "5️⃣ *Remarks or Special Conditions?*\n\n"
            "Please mention in ONE message:\n"
            "✅ Are you supplying the EXACT material, brand & spec as in the RFQ?\n"
            "✅ Any special conditions, warranty, or validity period?\n"
            "✅ Anything else the purchase team should know?\n\n"
            "Example: Yes, exact JSW material as per spec. Valid 7 days.\n"
            "         OR: Alternate brand Tata available, same quality, ISI marked.\n"
            "(Type SKIP if nothing to add)"
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
        f"1️⃣ *Brand / Make?*\n"
        f"(What brand of material are you providing?)\n"
        f"(Type SKIP to skip just this field)"
    )


def build_combined_total_question(total_mats: int) -> str:
    return (
        f"✅ Prices collected for all {total_mats} materials!\n\n"
        f"💰 *Combined Grand Total for the Complete Order?*\n"
        f"What is your best total price for *ALL {total_mats} materials together*?\n"
        f"(Include everything — GST, freight, loading/unloading, all charges)\n\n"
        f"Example: ₹1,25,000  or  125000  or  1.25 lakh\n\n"
        f"(Type SKIP if your individual material prices above are the final totals)"
    )


def build_summary_message(session: SupplierQuotationConversation, db: Session) -> str:
    data = session.collected_data or {}
    rfq = db.query(RFQ).filter(RFQ.id == session.rfq_id).first()
    rfq_number = rfq.rfq_number if rfq else (data.get("rfq_number") or "Unknown RFQ")

    lines = [f"📋 *Quotation Summary — {rfq_number}*", "Please review before submitting.\n"]

    materials = data.get("materials", [])
    items_total = 0.0

    for i, mat in enumerate(materials, 1):
        mat_name = mat.get("material_name", "Material")
        qty = mat.get("qty", "")
        unit = mat.get("unit", "")
        lines.append(f"*📦 Material {i}: {mat_name} ({qty} {unit})*")

        if mat.get("skipped"):
            lines.append("Status: ⏭️ Skipped\n")
            continue

        lines.append(f"1️⃣ Brand:       {mat.get('brand') or '—'}")

        tp = mat.get("total_price")
        if tp:
            try:
                tp_num = float(str(tp).replace(",", ""))
                items_total += tp_num
                lines.append(f"2️⃣ Total Price: ₹{tp_num:,.0f}  *(all-inclusive)*")
            except Exception:
                lines.append(f"2️⃣ Total Price: {tp}  *(all-inclusive)*")
        else:
            lines.append("2️⃣ Total Price: —")

        lines.append(f"3️⃣ Delivery:    {mat.get('delivery') or '—'}")
        lines.append(f"4️⃣ Payment:     {mat.get('payment_terms') or '—'}")
        lines.append(f"5️⃣ Remarks:     {mat.get('remarks_note') or '—'}")
        lines.append("")

    # Show combined/final total
    combined = data.get("combined_total")
    if combined:
        try:
            combined_num = float(str(combined).replace(",", ""))
            lines.append(f"💰 *Combined Total (All Materials): ₹{combined_num:,.0f}*")
            if items_total > 0 and abs(combined_num - items_total) > 1:
                diff = items_total - combined_num
                if diff > 0:
                    lines.append(f"   (Individual sum: ₹{items_total:,.0f} — bulk discount ₹{diff:,.0f})")
            lines.append("")
        except Exception:
            lines.append(f"💰 *Combined Total: {combined}*\n")
    elif items_total > 0:
        lines.append(f"💰 *Final Amount to Pay: ₹{items_total:,.0f}*")
        lines.append("")

    lines.append("✏️ *To change a field:*  CHANGE [Material No.] [Field No.]")
    lines.append("   Or just type two numbers, e.g.: *1 2*")
    lines.append("")
    lines.append("Fields: 1=Brand  2=Total Price  3=Delivery  4=Payment  5=Remarks")
    lines.append("")
    lines.append("Examples:")
    lines.append("• *1 2*  or  *CHANGE 1 2*  → Fix Material 1, Total Price")
    lines.append("• *1 3*  or  *CHANGE 1 3*  → Fix Material 1, Delivery")
    lines.append("• *1 5*  or  *CHANGE 1 5*  → Fix Material 1, Remarks")
    lines.append("")
    lines.append("✅ Type *CONFIRM* to submit your quotation")

    return "\n".join(lines)


# ── Session save ─────────────────────────────────────────────────────────────

def _generate_quotation_number(db: Session) -> str:
    """Generate next quotation number like QUO-2026-001."""
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

        # Mark any previous quotations from this vendor as not latest
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
        items_total = 0.0

        # Set header delivery/payment from first non-None material values
        delivery_val = next(
            (m.get("delivery") for m in materials if not m.get("skipped") and m.get("delivery")),
            None
        )
        payment_val = next(
            (m.get("payment_terms") for m in materials if not m.get("skipped") and m.get("payment_terms")),
            None
        )
        if delivery_val:
            quotation.delivery_timeline = delivery_val
        if payment_val:
            quotation.payment_terms = payment_val

        for mat in materials:
            if mat.get("skipped"):
                continue
            rfq_item_id = mat.get("rfq_item_id")
            try:
                total_price = float(str(mat.get("total_price", "0")).replace(",", "")) if mat.get("total_price") else None
                qty = float(str(mat.get("qty", "1")).replace(",", "")) if mat.get("qty") else 1.0
            except (ValueError, TypeError):
                total_price = None
                qty = 1.0

            if total_price:
                items_total += total_price

            # Per-unit landed rate = total_price / qty (all-inclusive per unit, for comparison ranking)
            final_rate = round(total_price / qty, 3) if (total_price and qty and qty > 0) else 0.0

            item = QuotationItem(
                quotation_id=quotation.id,
                rfq_item_id=rfq_item_id,
                brand_offered=mat.get("brand"),
                quoted_quantity=qty,
                basic_rate=0.0,           # Not collected separately — price is all-inclusive
                tax_percent=0.0,          # Not collected separately — price is all-inclusive
                total_item_amount=total_price or 0.0,
                final_landed_rate=final_rate,
                discount_percent=0.0,
                freight_amount=0.0,
                is_quoted=True,
                remarks=mat.get("remarks_note") or None,
            )
            db.add(item)

        # Use combined_total if supplier provided, else sum of individual totals
        combined_str = data.get("combined_total")
        if combined_str:
            try:
                quotation.grand_total = float(str(combined_str).replace(",", ""))
            except Exception:
                quotation.grand_total = items_total
        elif items_total > 0:
            quotation.grand_total = items_total

        db.commit()
        db.refresh(quotation)

        session.conversation_status = "COMPLETED"
        db.commit()

        logger.info(f"[QUOTATION] Saved {quotation_number} for RFQ {rfq.rfq_number}")
        return quotation

    except Exception as e:
        db.rollback()
        logger.error(f"[QUOTATION] Error saving quotation: {e}", exc_info=True)
        return None


# ── RFQ items helpers ────────────────────────────────────────────────────────

def _get_rfq_items(db: Session, rfq_id: int):
    return db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).order_by(RFQItem.id).all()


def _init_materials_in_data(data: dict, rfq_items) -> dict:
    """Populate materials array in collected_data from RFQ items."""
    data["materials"] = []
    for item in rfq_items:
        qty_str = ""
        if item.quantity:
            q = float(item.quantity)
            qty_str = str(int(q)) if q == int(q) else str(q)
        data["materials"].append({
            "rfq_item_id":   item.id,
            "material_name": item.material_name,
            "qty":           qty_str or "?",
            "unit":          item.unit or "unit",
            "brand":         None,
            "total_price":   None,
            "delivery":      None,
            "payment_terms": None,
            "remarks_note":  None,
            "skipped":       False,
        })
    return data


# ── Field answer parser ──────────────────────────────────────────────────────

def _parse_field_answer(field: str, text: str, mat: dict) -> Optional[str]:
    """
    Parse raw supplier text into a clean value for the given field.
    Returns None for total_price when no number found (triggers re-ask).
    All other fields always return a value (any text is valid).
    """
    text = text.strip()
    if field == "brand":
        return re.sub(r"^[-:*\s]+", "", text).strip() or text
    elif field == "total_price":
        return _parse_price_smart(text)  # None => re-ask
    elif field == "delivery":
        return _normalize_delivery(text)
    elif field == "payment_terms":
        return _normalize_payment(text)
    elif field == "remarks_note":
        return text
    return text


# ── Advance after field ──────────────────────────────────────────────────────

def _advance_after_field(db: Session, session: SupplierQuotationConversation,
                          data: dict, mat_idx: int, total_mats: int,
                          skip_material: bool = False) -> str:
    """Move session to the next step after answering/skipping a field."""
    materials = data.get("materials", [])

    # ★ If we are in "change mode" (came from CHANGE at summary), go straight back
    # to summary — do NOT continue the normal field-by-field flow.
    if data.get("_in_change_mode"):
        data["_in_change_mode"] = False
        session.collected_data = data
        flag_modified(session, "collected_data")
        session.current_step = "summary"
        db.commit()
        return build_summary_message(session, db)

    if skip_material:
        next_mat_idx = mat_idx + 1
        if next_mat_idx >= total_mats:
            if total_mats > 1:
                session.current_step = "combined_total"
                db.commit()
                return build_combined_total_question(total_mats)
            else:
                session.current_step = "summary"
                db.commit()
                return build_summary_message(session, db)
        else:
            session.current_material_index = next_mat_idx + 1
            session.current_step = f"m{next_mat_idx + 1}_brand"
            db.commit()
            return build_next_material_intro(materials[next_mat_idx], next_mat_idx + 1, total_mats)

    # Determine current field
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
        next_field = MATERIAL_FIELDS[next_field_idx]
        session.current_step = f"m{session.current_material_index}_{next_field}"
        db.commit()
        return build_field_question(next_field, materials[mat_idx], next_field_idx + 1)
    else:
        next_mat_idx = mat_idx + 1
        if next_mat_idx >= total_mats:
            if total_mats > 1:
                session.current_step = "combined_total"
                db.commit()
                return build_combined_total_question(total_mats)
            else:
                session.current_step = "summary"
                db.commit()
                return build_summary_message(session, db)
        else:
            session.current_material_index = next_mat_idx + 1
            session.current_step = f"m{next_mat_idx + 1}_brand"
            db.commit()
            return build_next_material_intro(materials[next_mat_idx], next_mat_idx + 1, total_mats)


# ── CHANGE handler at summary ─────────────────────────────────────────────────

def _handle_change_at_summary(mat_num: int, field_num: int, total_mats: int,
                               materials: list, session: SupplierQuotationConversation,
                               db: Session, data: dict = None) -> str:
    """Handle CHANGE mat_num field_num at the summary step."""
    if data is None:
        data = session.collected_data or {}
    n_fields = len(MATERIAL_FIELDS)
    if 1 <= mat_num <= total_mats and 1 <= field_num <= n_fields:
        target_field = MATERIAL_FIELDS[field_num - 1]
        target_mat = materials[mat_num - 1]
        current_val = target_mat.get(target_field) or "—"
        session.current_step = f"m{mat_num}_{target_field}"
        session.current_material_index = mat_num
        # ★ Set change mode flag so after answering, we go BACK to summary
        # instead of continuing the normal field flow (which could ask combined_total again)
        data["_in_change_mode"] = True
        session.collected_data = data
        flag_modified(session, "collected_data")
        db.commit()
        return (
            f"Updating:\n"
            f"Material {mat_num} — {target_mat.get('material_name', '')}\n"
            f"{field_num}️⃣ {FIELD_LABELS[target_field]}: {current_val}\n\n"
            f"What should it be?\n"
            f"(Type the new value, or SKIP to clear it)"
        )
    else:
        return (
            f"❓ Material must be 1–{total_mats}, field must be 1–{n_fields}.\n\n"
            f"Fields: 1=Brand  2=Total Price  3=Delivery  4=Payment  5=Remarks\n"
            f"Example: *1 2* → Fix Material 1, Total Price"
        )


# ── Core state machine ───────────────────────────────────────────────────────

def process_quotation_step(db: Session, session: SupplierQuotationConversation,
                            message_text: str, supplier: Supplier) -> str:
    """
    Core state machine. Given current session state and supplier message,
    returns the next reply string to send via WhatsApp.
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
                "Example: RFQ-2026-033\n\nType CANCEL to stop."
            )
        elif step in ("summary", "combined_total"):
            return (
                "📋 You are at the review step.\n\n"
                "• Type *CONFIRM* to submit ✅\n"
                "• Type *1 2* to fix Material 1, Total Price ✏️\n"
                "• Type *CANCEL* to cancel ❌\n\n"
                "Fields: 1=Brand  2=Total Price  3=Delivery  4=Payment  5=Remarks"
            )
        else:
            return (
                "📋 Just reply with your answer for the current question.\n"
                "Type SKIP to skip any field.\nType CANCEL to stop."
            )

    step = session.current_step

    # ── STEP: awaiting_rfq_number ────────────────────────────────────────────
    if step == "awaiting_rfq_number":
        if intent == "skip":
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
                    "Please check the RFQ number and try again."
                )

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
                "Example: RFQ-2026-033\nOr type HELP."
            )

    # ── Data references ──────────────────────────────────────────────────────
    materials = data.get("materials", [])
    total_mats = len(materials)
    mat_idx = session.current_material_index - 1  # 0-based

    # ── STEP: combined_total ─────────────────────────────────────────────────
    if step == "combined_total":
        if intent in ("skip", "confirm"):
            data["combined_total"] = None
            session.collected_data = data
            flag_modified(session, "collected_data")
            session.current_step = "summary"
            db.commit()
            return build_summary_message(session, db)

        combined_val = _parse_price_smart(text)
        if combined_val is None:
            return (
                "❓ Please type the combined total as a number.\n"
                "Example: ₹1,25,000  or  125000  or  1.25 lakh\n\n"
                "(Type SKIP to use individual material prices)"
            )
        data["combined_total"] = combined_val
        session.collected_data = data
        flag_modified(session, "collected_data")
        session.current_step = "summary"
        db.commit()
        return build_summary_message(session, db)

    # ── Boundary check ───────────────────────────────────────────────────────
    if mat_idx < 0 or mat_idx >= total_mats:
        session.current_step = "summary"
        db.commit()
        return build_summary_message(session, db)

    mat = materials[mat_idx]

    # Determine current field from step name, e.g. "m2_delivery" -> "delivery"
    field = None
    for f in MATERIAL_FIELDS:
        if step == f"m{session.current_material_index}_{f}":
            field = f
            break

    if field is None and step != "summary":
        session.current_step = "summary"
        db.commit()
        return build_summary_message(session, db)

    # ── SUMMARY step ─────────────────────────────────────────────────────────
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
                return _handle_change_at_summary(
                    int(m.group(1)), int(m.group(2)), total_mats, materials, session, db, data
                )
            return build_summary_message(session, db)

        else:
            # ── "X Y" / "X-Y" / "X,Y" → CHANGE X Y (supplier forgot keyword) ─
            two_num = _TWO_NUM_PATTERN.match(text)
            if two_num:
                return _handle_change_at_summary(
                    int(two_num.group(1)), int(two_num.group(2)),
                    total_mats, materials, session, db, data
                )

            # ── Partial CHANGE keyword (e.g. "change 5") ───────────────────
            if re.match(r"^\s*(change|chnage|cahnge|chane|chang|chenge|chaneg)\b",
                        text, re.IGNORECASE):
                return (
                    "✏️ Please specify *BOTH* the material number AND field number.\n\n"
                    "Format: *CHANGE [Material No.] [Field No.]*\n"
                    "   Or just type two numbers: e.g. *1 2*\n\n"
                    "Fields: 1=Brand  2=Total Price  3=Delivery  4=Payment  5=Remarks\n\n"
                    "Examples:\n"
                    "• *1 2*  or  *CHANGE 1 2*  → Fix Material 1, Total Price\n"
                    "• *1 5*  or  *CHANGE 1 5*  → Fix Material 1, Remarks\n\n"
                    "✅ Or type *CONFIRM* to submit your quotation"
                )

            # ── Single number ──────────────────────────────────────────────
            if re.match(r"^\s*\d+\s*$", text):
                return (
                    "✏️ To change a field, type *TWO* numbers: material number and field number.\n"
                    "Example: *1 2* → Fix Material 1, Total Price\n\n"
                    "✅ Or type *CONFIRM* to submit."
                )

            # ── Short unrecognized → "Did you mean?" ───────────────────────
            if len(text) <= 15:
                return (
                    "❓ Not sure what you mean. Please type one of:\n\n"
                    "• *CONFIRM* — to submit your quotation ✅\n"
                    "• *1 2* — to change Material 1, Total Price ✏️\n"
                    "• *CANCEL* — to cancel and start over ❌\n\n"
                    "Or type *HELP* for guidance."
                )

            # Long unrecognized → re-show summary
            return build_summary_message(session, db)

    # ── COLLECTING FIELD ─────────────────────────────────────────────────────

    # Brand SKIP = skip entire material
    if field == "brand" and intent == "skip":
        materials[mat_idx]["skipped"] = True
        session.collected_data = data
        flag_modified(session, "collected_data")
        return _advance_after_field(db, session, data, mat_idx, total_mats, skip_material=True)

    # Field-level skip
    if intent == "skip":
        materials[mat_idx][field] = None
        session.collected_data = data
        flag_modified(session, "collected_data")
        return _advance_after_field(db, session, data, mat_idx, total_mats)

    # Parse answer
    saved_value = _parse_field_answer(field, text, mat)

    # Validate total_price — re-ask if no number found
    if field == "total_price" and saved_value is None:
        return (
            "❓ I need a number for the total price.\n"
            "Please type the amount in rupees.\n"
            "Example: 43500  or  ₹43,500  or  43.5k  or  1.5 lakh\n\n"
            "(Type SKIP if you cannot provide a price right now)"
        )

    materials[mat_idx][field] = saved_value
    session.collected_data = data
    flag_modified(session, "collected_data")

    return _advance_after_field(db, session, data, mat_idx, total_mats)


# ── Entry point ──────────────────────────────────────────────────────────────

def handle_inbound_quotation_message(db: Session, supplier: Supplier,
                                      sender_phone: str, message_text: str) -> Optional[str]:
    """
    Main entry point called from the WhatsApp webhook.
    Returns the reply string if bot should respond, or None if silent.
    """
    text = (message_text or "").strip()

    # Continue active session
    session = get_active_session(db, sender_phone)
    if session:
        return process_quotation_step(db, session, text, supplier)

    # Start new session on QUOTE intent
    if detect_quote_start(text):
        if not supplier or supplier.registration_status != "APPROVED":
            return None

        session = create_session(db, sender_phone, supplier.id)
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
            db.commit()
            return "📝 *Starting Quotation*\n\n" + build_rfq_question()

        elif reason == "none":
            cancel_session(db, session)
            return (
                "❌ You don't have any open RFQs at the moment.\n"
                "Please contact your Purchase Manager."
            )
        else:
            db.commit()
            return "📝 *Starting Quotation*\n\n" + build_rfq_question()

    return None
