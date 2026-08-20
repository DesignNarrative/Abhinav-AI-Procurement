import os
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.database.database import SessionLocal

from app.models.supplier_conversation import (
    SupplierConversation
)
from app.models.supplier import Supplier
from app.models.whatsapp_inbox_message import WhatsAppInboxMessage

from app.models.supplier_reference import (
    SupplierReference
)

from app.services.supplier_mapper import (
    map_conversation_to_supplier
)

from app.services.whatsapp_media_service import (
    download_media
)

from app.services.validation_service import (
    validate_gst,
    validate_pan,
    validate_mobile,
    validate_email,
    validate_ifsc,
    validate_bank_account,
    validate_date
)

from app.whatsapp.registration_flow import (
    REGISTRATION_STEPS,
    QUESTION_MAP
)


from app.services.whatsapp_service import (
    send_text_message
)


from app.services.whatsapp_registration_service import (
    process_whatsapp_message
)





router = APIRouter(
    prefix="/whatsapp",
    tags=["WhatsApp Registration"]
)


def get_or_create_supplier(db: Session, sender_phone: str) -> Supplier:
    from app.services.whatsapp_service import normalize_phone_number
    normalized_sender_phone = normalize_phone_number(sender_phone)
    clean_phone_10 = normalized_sender_phone[-10:]

    supplier = db.query(Supplier).filter(
        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
        (Supplier.whatsapp_number == normalized_sender_phone)
    ).first()

    if not supplier:
        from app.api.supplier import generate_next_supplier_code
        supplier_code = generate_next_supplier_code(db)

        supplier = Supplier(
            supplier_code=supplier_code,
            company_name=f"WhatsApp Contact {sender_phone}",
            contact_person_name=f"WhatsApp Contact {sender_phone}",
            whatsapp_number=normalized_sender_phone,
            registration_status="PENDING_REGISTRATION",
            declaration_accepted=False,
            registered_address="Pending Registration",
            bank_name="Pending Registration",
            beneficiary_name="Pending Registration",
            bank_account_number="Pending Registration",
            bank_ifsc="Pending Registration"
        )
        try:
            db.add(supplier)
            db.commit()
            db.refresh(supplier)
            print(f"[AUTO-REGISTER] Created auto-approved supplier {sender_phone} with code {supplier_code}")
        except Exception as e:
            db.rollback()
            print(f"[AUTO-REGISTER] Failed to auto-register: {e}")
            supplier = db.query(Supplier).filter(
                (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                (Supplier.whatsapp_number == normalized_sender_phone)
            ).first()

    return supplier



@router.post("/start-registration")
def start_registration(
    phone_number: str,
    db: Session = Depends(get_db)
):

    existing_conversation = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.phone_number == phone_number,
        SupplierConversation.conversation_status == "IN_PROGRESS"
    ).first()

    if existing_conversation:
        return {
            "message": "Conversation already exists",
            "conversation_id": existing_conversation.id,
            "current_step": existing_conversation.current_step
        }

    conversation = SupplierConversation(
        phone_number=phone_number,
        current_step="company_name",
        collected_data={},
        conversation_status="IN_PROGRESS"
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    from app.services.whatsapp_registration_service import _get_dynamic_question
    q1_text = _get_dynamic_question("company_name", {})

    return {
        "message": "Supplier Registration Started",
        "conversation_id": conversation.id,
        "next_question": q1_text
    }


@router.post("/message")
def process_message(
    phone_number: str,
    answer: str,
    db: Session = Depends(get_db)
):

    conversation = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.phone_number == phone_number,
        SupplierConversation.conversation_status == "IN_PROGRESS"
    ).first()

    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="No active conversation found"
        )

    current_step = conversation.current_step

    data = conversation.collected_data or {}

    incoming_upper = answer.strip().upper()

    # ── Detect spelling typos for CHANGE command ──────────────────────────────
    from app.services.whatsapp_registration_service import _CHANGE_PATTERN, _CHANGE_TYPO_PATTERN, _STANDALONE_NUMBER_PATTERN
    typo_match = _CHANGE_TYPO_PATTERN.match(answer.strip())
    if typo_match and not _CHANGE_PATTERN.match(answer.strip()):
        question_num = int(typo_match.group(2))
        return {
            "error": f"Did you mean to change an answer? Please type exactly: CHANGE {question_num}"
        }

    # ── Detect standalone number shortcut at summary step ─────────────────────
    if current_step == "declaration_accepted":
        standalone_match = _STANDALONE_NUMBER_PATTERN.match(answer.strip())
        if standalone_match:
            question_num = int(standalone_match.group(1))
            # Translate standalone number to a perfect CHANGE N command
            answer = f"CHANGE {question_num}"
            incoming_upper = answer.strip().upper()

    # ── Handle CHANGE N command ───────────────────────────────────────────────
    change_match = _CHANGE_PATTERN.match(answer.strip())
    if change_match:
        question_num = int(change_match.group(1))
        # Build visible step list (respecting MSME skip for display)
        skipped_msme = str(data.get("is_msme", "")).upper() == "NO"
        from app.services.whatsapp_registration_service import _DATA_STEPS
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
            db.refresh(conversation)
            from app.services.whatsapp_registration_service import _get_dynamic_question
            q_text = _get_dynamic_question(target_step, data)
            return {
                "saved_field": "current_step",
                "saved_value": target_step,
                "next_step": target_step,
                "next_question": q_text
            }
        else:
            return {
                "error": f"Invalid number. Please type CHANGE followed by a number between 1 and {len(visible_steps)}."
            }

    # ── MSME Certificate — allow SKIP, reject other plain text ────────────────
    if current_step == "msme_certificate_path":
        if incoming_upper == "SKIP":
            data[current_step] = "SKIP"
        elif not (answer.startswith("uploads/") or answer.startswith("uploads\\")):
            return {
                "error": "Please upload a valid document or image file (PDF/JPG/PNG), or type SKIP."
            }

    # ── GST Certificate — mandatory, reject skip/plain text ───────────────────
    if current_step == "gst_certificate_path":
        if not (answer.startswith("uploads/") or answer.startswith("uploads\\")):
            return {
                "error": "GST Certificate is mandatory. Please upload a valid document or image file (PDF/JPG/PNG)."
            }

    # ── Declaration Submit step strict validation ────────────────────────────
    if current_step == "declaration_accepted":
        if incoming_upper != "YES":
            return {
                "error": "Please reply YES to submit, or type CHANGE [number] to edit an answer."
            }

    # Handle SKIP — save None for skippable fields
    if isinstance(answer, str) and answer.strip().upper() == "SKIP":
        data[current_step] = None

    # Convert Declaration to Boolean
    elif current_step == "declaration_accepted":
        data[current_step] = True

    else:
        data[current_step] = answer

    edit_mode = data.get("_edit_mode") is True

    # MSME Skip Logic: if answered NO, jump to gst_number (skip msme_number + msme_certificate_path)
    if current_step == "is_msme":
        from app.services.whatsapp_registration_service import _get_dynamic_question
        value = answer.strip().upper()
        data[current_step] = value
        if value == "NO":
            data["msme_number"] = None
            data["msme_certificate_path"] = None
            if edit_mode:
                data["_edit_mode"] = False
                conversation.collected_data = data
                conversation.current_step = "declaration_accepted"
                db.commit()
                db.refresh(conversation)
                return {
                    "saved_field": current_step,
                    "saved_value": False,
                    "next_step": "declaration_accepted",
                    "next_question": "Declaration summary shown"
                }
            else:
                conversation.collected_data = data
                conversation.current_step = "gst_number"
                db.commit()
                db.refresh(conversation)
                q_text = _get_dynamic_question("gst_number", data)
                return {
                    "saved_field": current_step,
                    "saved_value": False,
                    "next_step": "gst_number",
                    "next_question": q_text
                }
        else:
            conversation.collected_data = data
            conversation.current_step = "msme_number"
            db.commit()
            db.refresh(conversation)
            q_text = _get_dynamic_question("msme_number", data)
            return {
                "saved_field": current_step,
                "saved_value": True,
                "next_step": "msme_number",
                "next_question": QUESTION_MAP["msme_number"]
            }

    # Edit Mode Routing: Jump back to summary for other steps
    if edit_mode and current_step not in ("is_msme", "msme_number"):
        data["_edit_mode"] = False
        conversation.collected_data = data
        conversation.current_step = "declaration_accepted"
        db.commit()
        db.refresh(conversation)
        return {
            "saved_field": current_step,
            "saved_value": data.get(current_step),
            "next_step": "declaration_accepted",
            "next_question": "Declaration summary shown"
        }

    current_index = REGISTRATION_STEPS.index(current_step)
    next_index = current_index + 1

    # REGISTRATION COMPLETE
    if next_index >= len(REGISTRATION_STEPS):
        data.pop("_edit_mode", None)
        conversation.collected_data = data
        conversation.conversation_status = "COMPLETED"

        supplier_data = map_conversation_to_supplier(data)

        new_supplier = Supplier(**supplier_data)
        db.add(new_supplier)
        db.commit()
        db.refresh(new_supplier)

        return {
            "message": "Supplier Registration Completed",
            "reply": (
                f"✅ Registration completed successfully. Supplier ID: {new_supplier.id}\n\n"
                "Thank you for registering with Abhinav Group!\n\n"
                "💡 For any future updates to your registered information, please message this chat directly "
                "and our Purchase Manager will assist you manually."
            ),
            "supplier_id": new_supplier.id,
            "registration_status": new_supplier.registration_status
        }

    next_step = REGISTRATION_STEPS[next_index]

    conversation.collected_data = data
    conversation.current_step = next_step

    db.commit()
    db.refresh(conversation)

    from app.services.whatsapp_registration_service import _get_dynamic_question
    q_text = _get_dynamic_question(next_step, data)

    return {
        "saved_field": current_step,
        "saved_value": data.get(current_step),
        "next_step": next_step,
        "next_question": q_text
    }


@router.delete(
    "/reset-conversation/{phone_number}"
)
def reset_conversation(
    phone_number: str,
    db: Session = Depends(get_db)
):

    conversation = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.phone_number == phone_number
    ).first()

    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    db.delete(conversation)

    db.commit()

    return {
        "message": "Conversation reset successfully",
        "phone_number": phone_number
    }

@router.post("/test-complete-registration")
def test_complete_registration(
    db: Session = Depends(get_db)
):

    sample_data = {

        "company_name": "Test Supplier Pvt Ltd",
        "principal_business": "Construction Materials",
        "business_classification": "Manufacturer",

        "gst_number": "27ZZZZZ9999Z1Z5",
        "pan_number": "ZZZZZ9999Z",

        "date_of_incorporation": "2020-01-01",

        "registered_address": "Pune",
        "godown_address": "Chakan",

        "contact_person_name": "Rahul Sharma",
        "contact_person_mobile": "9876543299",
        "contact_person_email": "rahul@test.com",

        "telephone_number": "02012345678",
        "whatsapp_number": "9876543299",

        "supplier_category": "Civil Materials",
        "material_types": "Cement, Steel",

        "bank_account_name": "Test Supplier Pvt Ltd",
        "bank_account_number": "123456789123",

        "bank_ifsc": "ICIC0001234",
        "bank_name": "ICICI Bank",
        "branch_name": "Pune",

        "is_msme": True,
        "msme_number": "MSME123456",
        "msme_certificate_path": "uploads/msme.pdf",

        "gst_certificate_path": "uploads/gst.pdf",

        "reference_1_company": "ABC Builders",
        "reference_1_contact_person": "Rajesh Sharma",
        "reference_1_contact_number": "9876543210",

        "reference_2_company": "XYZ Infra",
        "reference_2_contact_person": "Amit Kumar",
        "reference_2_contact_number": "9988776655",

        "authorized_person_name": "Rahul Sharma",
        "designation": "Director",

        "declaration_accepted": True
    }

    existing_gst = db.query(
        Supplier
    ).filter(
        Supplier.gst_number ==
        sample_data["gst_number"]
    ).first()

    if existing_gst:
        return {
            "error": "Test supplier already exists"
        }

    supplier_data = map_conversation_to_supplier(
        sample_data
    )

    new_supplier = Supplier(
        **supplier_data
    )

    db.add(new_supplier)

    db.commit()

    db.refresh(new_supplier)
    
    reference_1 = SupplierReference(
        supplier_id=new_supplier.id,
        company_name=sample_data["reference_1_company"],
        contact_person=sample_data["reference_1_contact_person"],
        contact_number=sample_data["reference_1_contact_number"]
    )

    db.add(reference_1)

    reference_2 = SupplierReference(
        supplier_id=new_supplier.id,
        company_name=sample_data["reference_2_company"],
        contact_person=sample_data["reference_2_contact_person"],
        contact_number=sample_data["reference_2_contact_number"]
    )

    db.add(reference_2)

    db.commit()

    return {
        "message": "Test Supplier Created",
        "supplier_id": new_supplier.id,
        "registration_status": new_supplier.registration_status
    }
    
    
    
@router.get(
    "/conversation/{phone_number}"
)
def get_conversation(
    phone_number: str,
    db: Session = Depends(get_db)
):

    conversation = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.phone_number == phone_number
    ).first()

    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found"
        )

    return {
        "phone_number":
            conversation.phone_number,

        "current_step":
            conversation.current_step,

        "conversation_status":
            conversation.conversation_status,

        "collected_data":
            conversation.collected_data,

        "created_at":
            conversation.created_at,

        "updated_at":
            conversation.updated_at
    }
    
    
@router.get("/conversations")
def get_all_conversations(
    db: Session = Depends(get_db)
):

    conversations = db.query(
        SupplierConversation
    ).all()

    result = []

    for conversation in conversations:

        result.append({
            "phone_number":
                conversation.phone_number,

            "company_name":
                (
                    conversation.collected_data or {}
                ).get(
                    "company_name"
                ),

            "current_step":
                conversation.current_step,

            "status":
                conversation.conversation_status
        })

    return result


@router.get("/conversations/pending")
def get_pending_conversations(
    db: Session = Depends(get_db)
):

    conversations = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.conversation_status
        == "IN_PROGRESS"
    ).all()

    result = []

    for conversation in conversations:

        result.append({
            "phone_number":
                conversation.phone_number,

            "company_name":
                (
                    conversation.collected_data or {}
                ).get(
                    "company_name"
                ),

            "current_step":
                conversation.current_step
        })

    return result


@router.get("/dashboard")
def whatsapp_dashboard(
    db: Session = Depends(get_db)
):

    total_conversations = db.query(
        SupplierConversation
    ).count()

    in_progress = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.conversation_status
        == "IN_PROGRESS"
    ).count()

    completed = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.conversation_status
        == "COMPLETED"
    ).count()

    return {
        "total_conversations":
            total_conversations,

        "in_progress":
            in_progress,

        "completed":
            completed
    }
    

@router.get("/conversations/completed")
def get_completed_conversations(
    db: Session = Depends(get_db)
):

    conversations = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.conversation_status
        == "COMPLETED"
    ).all()

    result = []

    for conversation in conversations:

        result.append({

            "phone_number":
                conversation.phone_number,

            "company_name":
                (
                    conversation.collected_data or {}
                ).get(
                    "company_name"
                ),

            "status":
                conversation.conversation_status
        })

    return result

@router.get("/conversations/abandoned")
def get_abandoned_conversations(
    db: Session = Depends(get_db)
):

    conversations = db.query(
        SupplierConversation
    ).filter(
        SupplierConversation.conversation_status
        == "ABANDONED"
    ).all()

    result = []

    for conversation in conversations:

        result.append({

            "phone_number":
                conversation.phone_number,

            "company_name":
                (
                    conversation.collected_data or {}
                ).get(
                    "company_name"
                ),

            "status":
                conversation.conversation_status
        })

    return result


from fastapi import Request
from fastapi.responses import PlainTextResponse


@router.get("/webhook")
async def verify_webhook(request: Request):

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if (
        mode == "subscribe"
        and token == "abhinav_supplier_webhook_2026"
    ):
        return PlainTextResponse(challenge)

    raise HTTPException(
        status_code=403,
        detail="Verification failed"
    )


import hmac
import hashlib
from app.config.settings import META_APP_SECRET

def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    if not META_APP_SECRET:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    
    expected_sig = signature_header.split("sha256=")[1].strip()
    computed_sig = hmac.new(
        key=META_APP_SECRET.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(computed_sig, expected_sig)


@router.post("/webhook")
async def handle_inbound_webhook(request: Request, background_tasks: BackgroundTasks):
    db = SessionLocal()
    db_passed_to_background = False
    try:
        raw_body = await request.body()
        signature_header = request.headers.get("X-Hub-Signature-256")

        if META_APP_SECRET:
            if not verify_webhook_signature(raw_body, signature_header):
                raise HTTPException(status_code=403, detail="Signature verification failed.")

        import json
        body = json.loads(raw_body)

        print("--- INCOMING WHATSAPP PAYLOAD ---")

        import json

        print(json.dumps(body, indent=2))

        print("---------------------------------")

        entry = body["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        if "statuses" in value:
            status_entry = value["statuses"][0]
            wa_message_id = status_entry.get("id")
            wa_status = status_entry.get("status")  # sent, delivered, read, failed
            recipient_phone = status_entry.get("recipient_id")

            # Try to find the original outbound message
            inbox_msg = db.query(WhatsAppInboxMessage).filter(
                WhatsAppInboxMessage.whatsapp_message_id == wa_message_id
            ).first()

            if inbox_msg:
                # Update delivery status directly for the inbox view
                inbox_msg.delivery_status = wa_status
                if wa_status == "failed":
                    error_reason = "Meta Delivery Failed"
                    if "errors" in status_entry:
                        err = status_entry["errors"][0]
                        code = err.get("code")
                        title = err.get("title")
                        if code == 131047 or title == "Re-engagement message":
                            error_reason = "24h Window Closed (Vendor must message bot first)"
                        else:
                            error_reason = f"Failed ({title or 'Meta Error'})"
                    # Only append once
                    if "⚠️" not in inbox_msg.message_text:
                        inbox_msg.message_text = f"⚠️ {inbox_msg.message_text} — {error_reason}. Note: Images must be <5MB and videos <16MB."

                # Update the RFQVendor status if it exists
                from app.models.rfq_vendor import RFQVendor
                rv = db.query(RFQVendor).filter(
                    RFQVendor.vendor_id == inbox_msg.supplier_id
                ).order_by(RFQVendor.id.desc()).first()

                if rv:
                    if wa_status == "delivered":
                        rv.whatsapp_status = "Delivered"
                    elif wa_status == "read":
                        rv.whatsapp_status = "Read"
                    elif wa_status == "failed":
                        error_msg = "Failed"
                        if "errors" in status_entry:
                            err = status_entry["errors"][0]
                            code = err.get("code")
                            title = err.get("title")
                            if code == 131047 or title == "Re-engagement message":
                                error_msg = "Failed (24h Window Closed - Vendor must message bot first)"
                            else:
                                error_msg = f"Failed ({title or 'Meta Error'})"
                        rv.whatsapp_status = error_msg
                    
                db.commit()
                print(f"[STATUS] Updated message ID {inbox_msg.id} status to {wa_status}.")

            return {
                "status": "success"
            }

        if "messages" in value:

            message = value["messages"][0]

            print("MESSAGE TYPE =", message.get("type"))

            sender_phone = message["from"]

            # Resolve supplier and check if we should auto-resend failed or template RFQs
            supplier = get_or_create_supplier(db, sender_phone)
            if supplier and supplier.registration_status == "APPROVED":
                from app.models.rfq_vendor import RFQVendor
                from app.services.rfq_service import RFQService
                
                pending_rfqs = db.query(RFQVendor).filter(
                    RFQVendor.vendor_id == supplier.id,
                    (RFQVendor.whatsapp_status.like("Failed%") | (RFQVendor.whatsapp_status == "Sent (Template)"))
                ).all()
                
                for prv in pending_rfqs:
                    print(f"[AUTO-RESEND] Auto-resending RFQ {prv.rfq_id} to supplier {supplier.id} because 24h window opened.")
                    background_tasks.add_task(
                        RFQService.resend_rfq_to_specific_vendors,
                        db,
                        prv.rfq_id,
                        [supplier.id]
                    )

            if message.get("type") == "text":

                message_text = message.get("text", {}).get("body", "")

                # Get or create supplier record for this phone number
                supplier = get_or_create_supplier(db, sender_phone)
                normalized_sender_phone = supplier.whatsapp_number if supplier else sender_phone

                # ── STEP 1: Always log every inbound message to inbox ──────────
                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=normalized_sender_phone,
                        message_text=message_text,
                        direction="inbound",
                        is_read=False,
                        media_type="text"
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound text from {normalized_sender_phone}")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log inbound text: {e}")

                status = supplier.registration_status if supplier else "PENDING_REGISTRATION"

                # ── STEP 2: Route based on supplier status ─────────────────────

                # ── CASE A: APPROVED supplier ──────────────────────────────────
                if status == "APPROVED":
                    # Check if they have an active step-by-step quotation session
                    from app.services.whatsapp_quotation_service import (
                        get_active_session,
                        detect_quote_start,
                        handle_inbound_quotation_message,
                    )
                    active_quot_session = get_active_session(db, normalized_sender_phone)

                    if active_quot_session or detect_quote_start(message_text):
                        # Route to step-by-step quotation service
                        reply = handle_inbound_quotation_message(
                            db, supplier, normalized_sender_phone, message_text
                        )
                        if reply:
                            send_text_message(normalized_sender_phone, reply)
                    else:
                        # Casual / professional / any other message from APPROVED supplier
                        # Bot stays COMPLETELY SILENT — PM replies manually from inbox
                        print(f"[INBOX] Approved supplier {normalized_sender_phone} sent: {message_text[:80]} — bot silent")

                # ── CASE B: REJECTED supplier ──────────────────────────────────
                elif status == "REJECTED":
                    rejection_reply = (
                        "Hello! 🙏\n\n"
                        "Unfortunately your supplier registration with Abhinav Group "
                        "was not approved at this time.\n\n"
                        "Please contact our purchase department directly for further "
                        "assistance.\n\n"
                        "📞 Thank you for your interest. We appreciate your time."
                    )
                    send_text_message(normalized_sender_phone, rejection_reply)
                    print(f"[BOT] Sent rejection message to {normalized_sender_phone}")

                # ── CASE C: PENDING (submitted, awaiting PM review) ────────────
                elif status == "PENDING":
                    pending_reply = (
                        f"Hello! 🙏\n\n"
                        f"Your registration for *{supplier.company_name}* is currently "
                        f"under review by our purchase manager.\n\n"
                        f"We will notify you once a decision has been made. "
                        f"Thank you for your patience! ⏳"
                    )
                    send_text_message(normalized_sender_phone, pending_reply)
                    print(f"[BOT] Sent pending-review message to {normalized_sender_phone}")

                # ── CASE D: PENDING_REGISTRATION (new or deleted supplier) ─────
                else:
                    # Check for active registration conversation
                    active_reg_conv = db.query(SupplierConversation).filter(
                        SupplierConversation.phone_number == sender_phone,
                        SupplierConversation.conversation_status == "IN_PROGRESS"
                    ).first()

                    # Route to registration bot
                    response = process_whatsapp_message(
                        sender_phone,
                        message_text,
                        db
                    )
                    bot_reply = response.get("reply", "")
                    if bot_reply:
                        send_text_message(sender_phone, bot_reply)

            elif message.get("type") == "document":

                print("DOCUMENT RECEIVED")

                document = message["document"]
                filename = document.get("filename", "document.pdf")

                # Get or auto-create approved supplier
                supplier = get_or_create_supplier(db, sender_phone)
                normalized_sender_phone = supplier.whatsapp_number
                clean_phone_10 = normalized_sender_phone[-10:]

                # Download document to uploads/media directory for inbox rendering
                media_local_path = "uploads/media"
                file_path = None
                filename_only = None
                try:
                    file_path = download_media(document["id"], media_local_path, original_filename=filename)
                    filename_only = os.path.basename(file_path) if file_path else None
                except Exception as e:
                    print(f"[WHATSAPP] Failed to download inbound document: {e}")

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=normalized_sender_phone,
                        message_text=f"Received document: {filename}" if file_path else f"Received document: {filename} (download failed)",
                        direction="inbound",
                        is_read=False,
                        media_type="document" if file_path else "text",
                        media_path=f"uploads/media/{filename_only}" if file_path else None
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound document from {normalized_sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log document: {e}")

                conversation = db.query(
                    SupplierConversation
                ).filter(
                    SupplierConversation.phone_number
                    == sender_phone,
                    SupplierConversation.conversation_status
                    == "IN_PROGRESS"
                ).first()

                if not conversation:
                    if supplier and supplier.registration_status in ("APPROVED", "PENDING_REGISTRATION") and file_path:
                        # The file is already in uploads/media/ for inbox display.
                        # Copy it to uploads/quotation_documents/ so the pipeline can
                        # ingest, extract text, and classify it independently.
                        original_filename = document.get("filename", "document.pdf")
                        import shutil as _shutil
                        pipeline_dir = "uploads/quotation_documents"
                        os.makedirs(pipeline_dir, exist_ok=True)
                        pipeline_file_path = os.path.join(pipeline_dir, filename_only)
                        _shutil.copy2(file_path, pipeline_file_path)

                        from app.services.whatsapp_pipeline_service import process_whatsapp_document_pipeline
                        db_passed_to_background = True
                        background_tasks.add_task(
                            process_whatsapp_document_pipeline,
                            db,
                            sender_phone,
                            pipeline_file_path,
                            original_filename
                        )
                        # NOTE: No immediate send_text_message here.
                        # The pipeline sends receipt ONLY if classified as QUOTATION/INVOICE.
                    else:
                        if not file_path:
                            print("[WHATSAPP] Skipped document pipeline since download failed.")
                        else:
                            send_text_message(
                                sender_phone,
                                "No active registration found. Please register first."
                            )

                    return {
                        "status": "success"
                    }

                if conversation.current_step == (
                    "msme_certificate_path"
                ):

                    upload_folder = (
                        "uploads/msme"
                    )

                elif conversation.current_step == (
                    "gst_certificate_path"
                ):

                    upload_folder = (
                        "uploads/gst"
                    )

                else:

                    upload_folder = (
                        "uploads/misc"
                    )

                file_path = download_media(
                    document["id"],
                    upload_folder
                )

                response = process_whatsapp_message(
                    sender_phone,
                    file_path,
                    db
                )

                send_text_message(
                    sender_phone,
                    response["reply"]
                )
            
            elif message.get("type") == "image":

                print("IMAGE RECEIVED")

                image = message["image"]

                # Get or auto-create approved supplier
                supplier = get_or_create_supplier(db, sender_phone)
                normalized_sender_phone = supplier.whatsapp_number
                clean_phone_10 = normalized_sender_phone[-10:]

                # Download image to uploads/media directory for inbox rendering
                media_local_path = "uploads/media"
                file_path = None
                filename_only = None
                try:
                    file_path = download_media(image["id"], media_local_path, original_filename="image.jpg")
                    filename_only = os.path.basename(file_path) if file_path else None
                except Exception as e:
                    print(f"[WHATSAPP] Failed to download inbound image: {e}")

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=normalized_sender_phone,
                        message_text="Received photo" if file_path else "Received photo (download failed)",
                        direction="inbound",
                        is_read=False,
                        media_type="image" if file_path else "text",
                        media_path=f"uploads/media/{filename_only}" if file_path else None
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound image from {normalized_sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log image: {e}")

                conversation = db.query(
                    SupplierConversation
                ).filter(
                    SupplierConversation.phone_number == sender_phone,
                    SupplierConversation.conversation_status == "IN_PROGRESS"
                ).first()

                if not conversation:
                    if supplier and supplier.registration_status in ("APPROVED", "PENDING_REGISTRATION"):
                        # The file is already in uploads/media/ for inbox display.
                        # Copy it to uploads/quotation_documents/ so the pipeline can
                        # ingest, extract text (or Vision OCR), and classify it independently.
                        original_filename = os.path.basename(file_path)
                        import shutil as _shutil
                        pipeline_dir = "uploads/quotation_documents"
                        os.makedirs(pipeline_dir, exist_ok=True)
                        pipeline_file_path = os.path.join(pipeline_dir, filename_only)
                        _shutil.copy2(file_path, pipeline_file_path)

                        from app.services.whatsapp_pipeline_service import process_whatsapp_document_pipeline
                        db_passed_to_background = True
                        background_tasks.add_task(
                            process_whatsapp_document_pipeline,
                            db,
                            sender_phone,
                            pipeline_file_path,
                            original_filename
                        )
                        # NOTE: No immediate send_text_message here.
                        # The pipeline sends receipt ONLY if classified as QUOTATION/INVOICE.
                    else:
                        send_text_message(
                            sender_phone,
                            "No active registration found."
                        )

                    return {
                        "status": "success"
                    }

                if conversation.current_step == "msme_certificate_path":

                    upload_folder = "uploads/msme"

                elif conversation.current_step == "gst_certificate_path":

                    upload_folder = "uploads/gst"

                else:

                    upload_folder = "uploads/misc"

                file_path = download_media(
                    image["id"],
                    upload_folder
                )

                response = process_whatsapp_message(
                    sender_phone,
                    file_path,
                    db
                )

                send_text_message(
                    sender_phone,
                    response["reply"]
                )


            elif message.get("type") == "video":
                print("VIDEO RECEIVED")
                video = message["video"]

                # Get or auto-create approved supplier
                supplier = get_or_create_supplier(db, sender_phone)
                normalized_sender_phone = supplier.whatsapp_number
                clean_phone_10 = normalized_sender_phone[-10:]

                # Download video to uploads/media directory for inbox rendering
                media_local_path = "uploads/media"
                file_path = None
                filename_only = None
                try:
                    file_path = download_media(video["id"], media_local_path, original_filename="video.mp4")
                    filename_only = os.path.basename(file_path) if file_path else None
                except Exception as e:
                    print(f"[WHATSAPP] Failed to download inbound video: {e}")

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=normalized_sender_phone,
                        message_text="Received video" if file_path else "Received video (download failed)",
                        direction="inbound",
                        is_read=False,
                        media_type="video" if file_path else "text",
                        media_path=f"uploads/media/{filename_only}" if file_path else None
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound video from {normalized_sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log video: {e}")

                # Videos cannot be quotations — logged in inbox, PM handles from dashboard.
                print(f"[INBOX] Video from {normalized_sender_phone} — bot stays silent, PM will reply from inbox.")

            else:
                # Fallback for other media types (audio, voice, sticker, etc.)
                media_type = message.get("type")
                if media_type in message:
                    media_obj = message[media_type]
                    media_id = media_obj.get("id")

                    if media_id:
                        supplier = get_or_create_supplier(db, sender_phone)
                        normalized_sender_phone = supplier.whatsapp_number

                        media_local_path = "uploads/media"
                        file_path = None
                        filename_only = None
                        mime_type = media_obj.get("mime_type", "")
                        ext = ""
                        if "/" in mime_type:
                            ext = "." + mime_type.split("/")[1].split(";")[0]

                        filename = f"media_{media_id}{ext}"
                        try:
                            file_path = download_media(media_id, media_local_path, original_filename=filename)
                            filename_only = os.path.basename(file_path) if file_path else None
                        except Exception as e:
                            print(f"[WHATSAPP] Failed to download inbound fallback media ({media_type}): {e}")

                        try:
                            inbox_msg = WhatsAppInboxMessage(
                                supplier_id=supplier.id if supplier else None,
                                supplier_phone=normalized_sender_phone,
                                message_text=f"Received attachment ({media_type})" if file_path else f"Received attachment ({media_type}) (download failed)",
                                direction="inbound",
                                is_read=False,
                                media_type="document" if file_path and media_type not in ("image", "video") else ("video" if media_type == "video" else ("image" if media_type == "image" else "text")),
                                media_path=f"uploads/media/{filename_only}" if file_path else None
                            )
                            db.add(inbox_msg)
                            db.commit()
                            print(f"[INBOX] Logged inbound media ({media_type}) from {normalized_sender_phone} successfully.")
                        except Exception as e:
                            db.rollback()
                            print(f"[INBOX] Failed to log inbound media ({media_type}): {e}")

        return {
            "status": "success"
        }

    except HTTPException as he:
        raise he
    except Exception as e:

        print(
            f"Error reading webhook payload: {str(e)}"
        )

        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        if not db_passed_to_background:
            db.close()

