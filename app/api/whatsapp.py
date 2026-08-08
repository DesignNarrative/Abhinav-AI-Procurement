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

        if "messages" in value:

            message = value["messages"][0]

            print("MESSAGE TYPE =", message.get("type"))

            sender_phone = message["from"]

            if message.get("type") == "text":

                message_text = message.get(
                    "text",
                    {}
                ).get(
                    "body",
                    ""
                )

                # Decide whether this text belongs to the registration flow or
                # is a plain-text quotation from an already-approved supplier.
                active_conversation = db.query(
                    SupplierConversation
                ).filter(
                    SupplierConversation.phone_number == sender_phone,
                    SupplierConversation.conversation_status == "IN_PROGRESS"
                ).first()

                # Log inbound message to inbox DB (for all numbers - approved or registering)
                from app.services.whatsapp_service import normalize_phone_number
                normalized_sender_phone = normalize_phone_number(sender_phone)
                clean_phone_10 = normalized_sender_phone[-10:]
                supplier = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == normalized_sender_phone)
                ).first()

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
                    print(f"[INBOX] Logged inbound text from {normalized_sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log inbound text: {e}")

                incoming = (message_text or "").strip().upper()
                registration_keywords = ["HI", "HELLO", "HII", "HEY", "HELO", "HAI", "HIYA", "START"]

                routed_to_quotation = False
                bot_should_stay_silent = False

                # Check if sender is an approved supplier first (before checking registration keywords)
                supplier_approved = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == sender_phone)
                ).filter(
                    Supplier.registration_status == "APPROVED"
                ).first()

                if supplier_approved:
                    text_lower = (message_text or "").lower()
                    quotation_signals = [
                        "quotation", "quote", "rate", "price", "amount",
                        "gst", "\u20b9", "rs", "per ", "qty", "nos"
                    ]
                    looks_like_quotation = any(sig in text_lower for sig in quotation_signals)

                    if looks_like_quotation:
                        from app.services.whatsapp_pipeline_service import process_whatsapp_text_quotation
                        db_passed_to_background = True
                        background_tasks.add_task(
                            process_whatsapp_text_quotation,
                            db,
                            sender_phone,
                            message_text
                        )
                        send_text_message(
                            sender_phone,
                            "We have received your quotation and our AI is processing it. You will receive a confirmation shortly."
                        )
                        routed_to_quotation = True
                    else:
                        # Approved supplier sending a casual text — not a quotation.
                        # Bot stays silent; PM replies manually from the dashboard inbox.
                        print(f"[INBOX] Casual message from approved supplier {sender_phone}: {message_text[:80]}")
                        bot_should_stay_silent = True

                if not routed_to_quotation and not bot_should_stay_silent:
                    response = process_whatsapp_message(
                        sender_phone,
                        message_text,
                        db
                    )

                    send_text_message(
                        sender_phone,
                        response["reply"]
                    )

            elif message.get("type") == "document":

                print("DOCUMENT RECEIVED")

                document = message["document"]
                filename = document.get("filename", "document.pdf")

                # Log inbound document to inbox DB
                from app.services.whatsapp_service import normalize_phone_number
                normalized_sender_phone = normalize_phone_number(sender_phone)
                clean_phone_10 = normalized_sender_phone[-10:]
                supplier = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == normalized_sender_phone)
                ).first()

                # Download document to uploads/media directory for inbox rendering
                media_local_path = "uploads/media"
                file_path = download_media(document["id"], media_local_path, original_filename=filename)
                filename_only = os.path.basename(file_path)

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=normalized_sender_phone,
                        message_text=f"Received document: {filename}",
                        direction="inbound",
                        is_read=False,
                        media_type="document",
                        media_path=f"uploads/media/{filename_only}"
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
                    # Check if sender is an approved supplier
                    clean_phone = sender_phone.replace("+", "").strip()
                    clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
                    supplier = db.query(Supplier).filter(
                        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                        (Supplier.whatsapp_number == sender_phone)
                    ).filter(
                        Supplier.registration_status == "APPROVED"
                    ).first()

                    if supplier:
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
                        send_text_message(
                            sender_phone,
                            "No active registration found."
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

                # Log inbound image to inbox DB
                from app.services.whatsapp_service import normalize_phone_number
                normalized_sender_phone = normalize_phone_number(sender_phone)
                clean_phone_10 = normalized_sender_phone[-10:]
                supplier = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == normalized_sender_phone)
                ).first()

                # Download image to uploads/media directory for inbox rendering
                media_local_path = "uploads/media"
                file_path = download_media(image["id"], media_local_path, original_filename="image.jpg")
                filename_only = os.path.basename(file_path)

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=normalized_sender_phone,
                        message_text="Received photo",
                        direction="inbound",
                        is_read=False,
                        media_type="image",
                        media_path=f"uploads/media/{filename_only}"
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
                    # Check if sender is an approved supplier
                    clean_phone = sender_phone.replace("+", "").strip()
                    clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
                    supplier = db.query(Supplier).filter(
                        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                        (Supplier.whatsapp_number == sender_phone)
                    ).filter(
                        Supplier.registration_status == "APPROVED"
                    ).first()

                    if supplier:
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

                from app.services.whatsapp_service import normalize_phone_number
                normalized_sender_phone = normalize_phone_number(sender_phone)
                clean_phone_10 = normalized_sender_phone[-10:]
                supplier = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == normalized_sender_phone)
                ).first()

                # Download video to uploads/media directory for inbox rendering
                media_local_path = "uploads/media"
                file_path = download_media(video["id"], media_local_path, original_filename="video.mp4")
                filename_only = os.path.basename(file_path)

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=normalized_sender_phone,
                        message_text="Received video",
                        direction="inbound",
                        is_read=False,
                        media_type="video",
                        media_path=f"uploads/media/{filename_only}"
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound video from {normalized_sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log video: {e}")

                # Videos cannot be quotations — logged in inbox, PM handles from dashboard.
                print(f"[INBOX] Video from {normalized_sender_phone} — bot stays silent, PM will reply from inbox.")

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
