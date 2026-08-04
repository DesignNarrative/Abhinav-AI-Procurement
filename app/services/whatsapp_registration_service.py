from sqlalchemy.orm import Session



from app.models.supplier_conversation import (
    SupplierConversation
)

from app.whatsapp.registration_flow import (
    WELCOME_MESSAGE,
    QUESTION_MAP,
    REGISTRATION_STEPS
)



from app.models.supplier import Supplier



from app.services.supplier_mapper import (
    map_conversation_to_supplier
)

from app.services.validation_service import (
    validate_gst,
    validate_mobile,
    validate_email,
    validate_ifsc,
    validate_bank_account
)

def process_whatsapp_message(
    phone_number: str,
    message_text: str,
    db: Session
):
    # Check if this sender is PENDING or REJECTED — give them a status reply.
    # NOTE: APPROVED suppliers are handled entirely by the webhook before this
    # function is called, so they never reach here. The bot stays silent for
    # approved suppliers chatting casually — the PM replies manually on WhatsApp.
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

    incoming_message = (
        message_text.strip().upper()
    )

    if not conversation:

        if incoming_message in [
            "HI",
            "HELLO",
            "HII"
        ]:

            return {
                "reply": WELCOME_MESSAGE
            }

        if incoming_message == "START":

            conversation = SupplierConversation(
                phone_number=phone_number,
                current_step="company_name",
                collected_data={},
                conversation_status="IN_PROGRESS"
            )

            db.add(conversation)

            db.commit()

            db.refresh(conversation)

            return {
                "reply":
                    QUESTION_MAP["company_name"]
            }

        return {
            "reply":
                "Please send HI to start supplier registration."
        }

    current_step = conversation.current_step

    data = conversation.collected_data or {}

    # MSME Certificate Skip Logic
    if current_step == "msme_certificate_path":

        if message_text.upper() == "SKIP":

            data[current_step] = "SKIP"

            current_index = REGISTRATION_STEPS.index(
                current_step
            )

            next_step = REGISTRATION_STEPS[
                current_index + 1
            ]

            conversation.collected_data = data
            conversation.current_step = next_step

            db.commit()

            return {
                "reply":
                    QUESTION_MAP[next_step]
            }
    
    # GST Certificate Mandatory
    if current_step == "gst_certificate_path":

        if message_text.upper() == "SKIP":

            return {
                "reply":
                "GST Certificate is mandatory. Please upload GST Registration Certificate."
            }
    
    
    # GST Validation
    if current_step == "gst_number":

        if not validate_gst(message_text):

            return {
                "reply":
                "Invalid GST Number. Please enter a valid GST Number."
            }

        existing_supplier = db.query(
            Supplier
        ).filter(
            Supplier.gst_number == message_text.upper()
        ).first()

        if existing_supplier:

            return {
                "reply":
                "This GST Number is already registered. Please enter another GST Number."
            }

    # Email Validation
    if current_step == "contact_person_email":

        if (
            message_text.upper() != "SKIP"
            and not validate_email(message_text)
        ):

            return {
                "reply":
                "Invalid Email Address. Enter a valid email or type SKIP."
            }

    # Mobile Validation
    if current_step == "whatsapp_number":

        if not validate_mobile(message_text):

            return {
                "reply":
                "Invalid Mobile Number. Please enter a 10 digit mobile number."
            }

    # Bank Account Validation
    if current_step == "bank_account_number":

        if not validate_bank_account(message_text):

            return {
                "reply":
                "Invalid Bank Account Number. Please enter Correct Bank Account Number."
            }

    # IFSC Validation
    if current_step == "bank_ifsc":

        if not validate_ifsc(message_text):

            return {
                "reply":
                "Invalid IFSC Code. Please enter a valid IFSC Code."
            }
    
    data[current_step] = message_text

    current_index = REGISTRATION_STEPS.index(
        current_step
    )

    next_index = current_index + 1

    if next_index >= len(
        REGISTRATION_STEPS
    ):

        conversation.collected_data = data

        supplier_data = map_conversation_to_supplier(
            data
        )

        try:

            new_supplier = Supplier(
                **supplier_data
            )

            db.add(new_supplier)

            db.flush()

            conversation.conversation_status = (
                "COMPLETED"
            )

            db.commit()

            return {
                "reply":
                    f"Registration completed successfully. Supplier ID: {new_supplier.id}"
            }

        except Exception as e:

            db.rollback()

            return {
                "reply":
                    f"Registration failed: {str(e)}"
            }

    next_step = REGISTRATION_STEPS[
        next_index
    ]

    conversation.collected_data = data

    conversation.current_step = next_step

    db.commit()

    return {
        "reply":
            QUESTION_MAP[next_step]
    }
    
    
    
    