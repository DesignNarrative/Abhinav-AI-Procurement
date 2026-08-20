import re
from sqlalchemy.orm import Session

from app.models.supplier_conversation import SupplierConversation
from app.whatsapp.registration_flow import (
    WELCOME_MESSAGE,
    QUESTION_MAP,
    REGISTRATION_STEPS,
    STEP_LABELS,
    STEP_EMOJIS
)
from app.models.supplier import Supplier
from app.services.supplier_mapper import map_conversation_to_supplier


# Greeting words that trigger the welcome message
_GREETING_WORDS = {"HI", "HELLO", "HII", "HEY", "HELO", "HAI", "HIYA", "HELO"}

# Regex to detect CHANGE N command (e.g. "CHANGE 3", "change5", "Change 5")
_CHANGE_PATTERN = re.compile(r"^\s*CHANGE\s*(\d+)\s*$", re.IGNORECASE)

# Regex to detect CHANGE N spelling typos (e.g. "changes13", "changed 14")
_CHANGE_TYPO_PATTERN = re.compile(
    r"^\s*(change|changes|changed|chaneg|chagne|chang|cheng|cahnde|chanel)\s*?(\d+)\s*$",
    re.IGNORECASE
)

# Regex to detect a standalone number (only used at the summary step)
_STANDALONE_NUMBER_PATTERN = re.compile(r"^\s*(\d+)\s*$")

# Data steps (excluding declaration) used when building summary
_DATA_STEPS = REGISTRATION_STEPS[:-1]  # everything except "declaration_accepted"


def _get_dynamic_question(step: str, data: dict) -> str:
    """Helper to dynamically calculate the sequential number prefix for a step."""
    visible_steps = []
    skipped_msme = str(data.get("is_msme", "")).upper() == "NO"
    for s in REGISTRATION_STEPS:
        if skipped_msme and s in ("msme_number", "msme_certificate_path"):
            continue
        visible_steps.append(s)

    try:
        visible_index = visible_steps.index(step) + 1
    except ValueError:
        visible_index = 1

    emoji = STEP_EMOJIS[visible_index - 1] if visible_index <= len(STEP_EMOJIS) else f"{visible_index}."
    question_text = QUESTION_MAP.get(step, step)
    return f"{emoji} {question_text}"


def _build_summary(data: dict, skipped_msme: bool) -> str:
    """Build a numbered summary of all collected answers for review."""
    lines = ["📋 *Registration Summary — Please review before submitting:*\n"]
    display_index = 1
    for step in _DATA_STEPS:
        # Skip MSME sub-questions if MSME was answered NO
        if skipped_msme and step in ("msme_number", "msme_certificate_path"):
            continue
        value = data.get(step)
        label = STEP_LABELS.get(step, step)
        if value is None or str(value).upper() in ("SKIP", ""):
            display_value = "—"
        elif step == "msme_certificate_path" or step == "gst_certificate_path":
            display_value = "Uploaded ✅" if value and str(value).upper() not in ("SKIP", "NONE") else "Not uploaded"
        else:
            display_value = str(value)
        emoji = STEP_EMOJIS[display_index - 1] if display_index <= len(STEP_EMOJIS) else f"{display_index}."
        lines.append(f"{emoji} {label}: {display_value}")
        display_index += 1

    lines.append(
        "\n📝 *To change any answer, type:*\n"
        "CHANGE [number]  (e.g. CHANGE 3 to change Materials)\n"
    )
    lines.append("Or reply *YES* to confirm and submit your registration.")
    return "\n".join(lines)


def process_whatsapp_message(
    phone_number: str,
    message_text: str,
    db: Session
):
    """
    Main entry point for all inbound WhatsApp messages from non-approved senders.
    Handles:
      - Greetings → welcome message
      - START → begin registration
      - CHANGE N → correct a previous answer
      - Normal answers → advance registration step by step
    """
    # Check if this sender is PENDING or REJECTED — give them a status reply.
    clean_phone = phone_number.replace("+", "").strip()
    clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
    supplier = db.query(Supplier).filter(
        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
        (Supplier.whatsapp_number == phone_number)
    ).first()

    if supplier:
        if supplier.registration_status == "PENDING":
            return {
                "reply": f"Hello! Your registration application for {supplier.company_name} is currently under review by our purchase manager. We will notify you once it is approved! ⏳"
            }
        elif supplier.registration_status == "REJECTED":
            return {
                "reply": f"Hello! Your registration application for {supplier.company_name} was unfortunately not approved. Please contact the purchase department for support. 📞"
            }

    conversation = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.phone_number == phone_number,
        SupplierConversation.conversation_status == "IN_PROGRESS"
    ).first()

    incoming_upper = message_text.strip().upper()

    # ── No active conversation ────────────────────────────────────────────────
    if not conversation:

        if incoming_upper in _GREETING_WORDS or incoming_upper == "REGISTER":
            return {"reply": WELCOME_MESSAGE}

        if incoming_upper == "START":
            conversation = SupplierConversation(
                phone_number=phone_number,
                current_step="company_name",
                collected_data={},
                conversation_status="IN_PROGRESS"
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            # Dynamic calculation for Q1
            q1_text = _get_dynamic_question("company_name", {})
            return {"reply": q1_text}

        return {
            "reply": "Please send HI to start supplier registration."
        }

    # ── Active conversation ───────────────────────────────────────────────────
    current_step = conversation.current_step
    data = conversation.collected_data or {}
    edit_mode = data.get("_edit_mode") is True

    # Determine if MSME was skipped (answered NO)
    skipped_msme = str(data.get("is_msme", "")).upper() == "NO"

    # ── Detect spelling typos for CHANGE command ──────────────────────────────
    typo_match = _CHANGE_TYPO_PATTERN.match(message_text.strip())
    if typo_match and not _CHANGE_PATTERN.match(message_text.strip()):
        question_num = int(typo_match.group(2))
        return {
            "reply": f"💡 Did you mean to change an answer? Please type exactly: CHANGE {question_num}"
        }

    # ── Detect standalone number shortcut at summary step ─────────────────────
    if current_step == "declaration_accepted":
        standalone_match = _STANDALONE_NUMBER_PATTERN.match(message_text.strip())
        if standalone_match:
            question_num = int(standalone_match.group(1))
            # Translate standalone number to a perfect CHANGE N command
            message_text = f"CHANGE {question_num}"

    # ── Handle CHANGE N command ───────────────────────────────────────────────
    change_match = _CHANGE_PATTERN.match(message_text.strip())
    if change_match:
        question_num = int(change_match.group(1))
        # Build visible step list (respecting MSME skip for display)
        visible_steps = []
        for s in _DATA_STEPS:
            if skipped_msme and s in ("msme_number", "msme_certificate_path"):
                continue
            visible_steps.append(s)

        if 1 <= question_num <= len(visible_steps):
            target_step = visible_steps[question_num - 1]
            data["_edit_mode"] = True
            conversation.collected_data = data
            conversation.current_step = target_step
            db.commit()
            q_text = _get_dynamic_question(target_step, data)
            return {"reply": q_text}
        else:
            return {
                "reply": f"Invalid number. Please type CHANGE followed by a number between 1 and {len(visible_steps)}.\n\nExample: CHANGE 3"
            }

    # ── MSME Certificate — allow SKIP, reject other plain text ────────────────
    if current_step == "msme_certificate_path":
        if incoming_upper == "SKIP":
            data[current_step] = "SKIP"
            if edit_mode:
                data["_edit_mode"] = False
                conversation.collected_data = data
                conversation.current_step = "declaration_accepted"
                db.commit()
                skipped_msme_final = str(data.get("is_msme", "")).upper() == "NO"
                summary = _build_summary(data, skipped_msme_final)
                return {"reply": summary}
            else:
                current_index = REGISTRATION_STEPS.index(current_step)
                next_step = REGISTRATION_STEPS[current_index + 1]
                conversation.collected_data = data
                conversation.current_step = next_step
                db.commit()
                q_text = _get_dynamic_question(next_step, data)
                return {"reply": q_text}
        elif not (message_text.startswith("uploads/") or message_text.startswith("uploads\\")):
            return {
                "reply": "Invalid input. Please upload your MSME Certificate as a document or image file (PDF/JPG/PNG), or type SKIP."
            }

    # ── GST Certificate — mandatory, reject skip/plain text ───────────────────
    if current_step == "gst_certificate_path":
        if not (message_text.startswith("uploads/") or message_text.startswith("uploads\\")):
            return {
                "reply": "Invalid input. GST Certificate is mandatory. Please upload it as a document or image file (PDF/JPG/PNG)."
            }

    # ── Declaration Submit step strict validation ────────────────────────────
    if current_step == "declaration_accepted":
        if incoming_upper != "YES":
            skipped_msme_final = str(data.get("is_msme", "")).upper() == "NO"
            summary = _build_summary(data, skipped_msme_final)
            return {
                "reply": (
                    "⚠️ *Invalid Option.*\n"
                    "Please reply *YES* to confirm and submit, or type *CHANGE [number]* to edit an answer.\n\n"
                    f"{summary}"
                )
            }

    # ── Save the answer for the current step ─────────────────────────────────
    data[current_step] = message_text

    # ── MSME Skip/Branching Logic ─────────────────────────────────────────────
    if current_step == "is_msme":
        value = incoming_upper
        data["is_msme"] = value
        if value == "NO":
            data["msme_number"] = None
            data["msme_certificate_path"] = None
            if edit_mode:
                data["_edit_mode"] = False
                conversation.collected_data = data
                conversation.current_step = "declaration_accepted"
                db.commit()
                skipped_msme_final = str(data.get("is_msme", "")).upper() == "NO"
                summary = _build_summary(data, skipped_msme_final)
                return {"reply": summary}
            else:
                conversation.collected_data = data
                conversation.current_step = "gst_number"
                db.commit()
                q_text = _get_dynamic_question("gst_number", data)
                return {"reply": q_text}
        else:
            # Answered YES: must ask MSME Number
            conversation.collected_data = data
            conversation.current_step = "msme_number"
            db.commit()
            q_text = _get_dynamic_question("msme_number", data)
            return {"reply": q_text}

    # ── Edit Mode Routing (Jump back to summary for other steps) ─────────────
    if edit_mode and current_step not in ("is_msme", "msme_number"):
        data["_edit_mode"] = False
        conversation.collected_data = data
        conversation.current_step = "declaration_accepted"
        db.commit()
        skipped_msme_final = str(data.get("is_msme", "")).upper() == "NO"
        summary = _build_summary(data, skipped_msme_final)
        return {"reply": summary}

    current_index = REGISTRATION_STEPS.index(current_step)
    next_index = current_index + 1

    # ── Registration complete ─────────────────────────────────────────────────
    if next_index >= len(REGISTRATION_STEPS):
        data.pop("_edit_mode", None)  # Clean up edit flag
        conversation.collected_data = data
        supplier_data = map_conversation_to_supplier(data)
        supplier_data["whatsapp_number"] = phone_number
        try:
            # Find the existing supplier created as a placeholder
            clean_phone = phone_number.replace("+", "").strip()
            clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
            supplier = db.query(Supplier).filter(
                (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                (Supplier.whatsapp_number == phone_number)
            ).first()

            if supplier:
                # Update attributes in place
                for k, v in supplier_data.items():
                    setattr(supplier, k, v)
            else:
                supplier = Supplier(**supplier_data)
                db.add(supplier)

            db.flush()
            conversation.conversation_status = "COMPLETED"
            db.commit()
            return {
                "reply": (
                    f"✅ Registration completed successfully. Supplier ID: {supplier.id}\n\n"
                    "Thank you for registering with Abhinav Group!\n\n"
                    "💡 For any future updates to your registered information, please message this chat directly "
                    "and our Purchase Manager will assist you manually."
                )
            }
        except Exception as e:
            db.rollback()
            return {
                "reply": f"Registration failed: {str(e)}"
            }

    next_step = REGISTRATION_STEPS[next_index]

    # ── Show summary before declaration ──────────────────────────────────────
    if next_step == "declaration_accepted":
        conversation.collected_data = data
        conversation.current_step = next_step
        db.commit()
        skipped_msme_final = str(data.get("is_msme", "")).upper() == "NO"
        summary = _build_summary(data, skipped_msme_final)
        return {"reply": summary}

    # ── Normal advance to next step ───────────────────────────────────────────
    conversation.collected_data = data
    conversation.current_step = next_step
    db.commit()
    q_text = _get_dynamic_question(next_step, data)
    return {"reply": q_text}