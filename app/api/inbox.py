from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel

from app.database.dependencies import get_db
from app.models.supplier import Supplier
from app.models.supplier_conversation import SupplierConversation
from app.models.whatsapp_inbox_message import WhatsAppInboxMessage
from app.services.whatsapp_service import send_text_message


router = APIRouter(
    prefix="/inbox",
    tags=["WhatsApp Inbox"]
)


# ---------------------------------------------------------------------------
# GET /inbox/unread-count
# Returns total unread inbound message count (for sidebar badge)
# ---------------------------------------------------------------------------
@router.get("/unread-count")
def get_unread_count(db: Session = Depends(get_db)):
    count = db.query(WhatsAppInboxMessage).filter(
        WhatsAppInboxMessage.direction == "inbound",
        WhatsAppInboxMessage.is_read == False
    ).count()
    return {"unread_count": count}


# ---------------------------------------------------------------------------
# GET /inbox/conversations
# Returns list of all unique phone numbers who have inbox messages,
# with their last message, display name, and unread count
# ---------------------------------------------------------------------------
@router.get("/conversations")
def get_conversations(db: Session = Depends(get_db)):
    # Get all unique supplier phone numbers that have at least one inbox message
    phone_rows = db.query(WhatsAppInboxMessage.supplier_phone).distinct().all()
    phones = [row[0] for row in phone_rows]

    conversations = []
    for phone in phones:
        # Clean phone number to look up in Supplier table
        clean_phone = phone.replace("+", "").strip()
        clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
        
        supplier = db.query(Supplier).filter(
            (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
            (Supplier.whatsapp_number == phone)
        ).first()

        # Determine display name and details
        company_name = f"New Supplier (+{phone})"
        contact_person = "Unregistered"
        supplier_id = None

        if supplier:
            company_name = supplier.company_name
            contact_person = supplier.contact_person_name or "Approved"
            supplier_id = supplier.id
        else:
            # Check if they are currently registering (in active conversation)
            active_conv = db.query(SupplierConversation).filter(
                (SupplierConversation.phone_number == phone) |
                (SupplierConversation.phone_number.like(f"%{clean_phone_10}"))
            ).filter(
                SupplierConversation.conversation_status == "IN_PROGRESS"
            ).first()
            if active_conv and active_conv.collected_data:
                # If they have typed their company name already, show it
                draft_name = active_conv.collected_data.get("company_name")
                if draft_name:
                    company_name = f"{draft_name} (Registering...)"
                    contact_person = "Registering Onboard"

        last_msg = db.query(WhatsAppInboxMessage).filter(
            WhatsAppInboxMessage.supplier_phone == phone
        ).order_by(desc(WhatsAppInboxMessage.created_at)).first()

        unread = db.query(WhatsAppInboxMessage).filter(
            WhatsAppInboxMessage.supplier_phone == phone,
            WhatsAppInboxMessage.direction == "inbound",
            WhatsAppInboxMessage.is_read == False
        ).count()

        conversations.append({
            "supplier_id": supplier_id,
            "supplier_phone": phone,
            "company_name": company_name,
            "contact_person": contact_person,
            "whatsapp_number": phone,
            "last_message": last_msg.message_text[:80] if last_msg else "",
            "last_message_direction": last_msg.direction if last_msg else "",
            "last_message_time": last_msg.created_at.isoformat() if last_msg else "",
            "unread_count": unread
        })

    # Sort by most recent message first
    conversations.sort(key=lambda x: x["last_message_time"], reverse=True)
    return conversations


# ---------------------------------------------------------------------------
# GET /inbox/conversations/{phone_number}
# Returns all messages in a conversation with a specific phone number
# ---------------------------------------------------------------------------
@router.get("/conversations/{phone_number}")
def get_conversation_messages(
    phone_number: str,
    db: Session = Depends(get_db)
):
    clean_phone = phone_number.replace("+", "").strip()
    clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
    
    supplier = db.query(Supplier).filter(
        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
        (Supplier.whatsapp_number == phone_number)
    ).first()

    company_name = f"New Supplier (+{phone_number})"
    contact_person = "Unregistered"
    supplier_id = None

    if supplier:
        company_name = supplier.company_name
        contact_person = supplier.contact_person_name or "Approved"
        supplier_id = supplier.id
    else:
        active_conv = db.query(SupplierConversation).filter(
            (SupplierConversation.phone_number == phone_number) |
            (SupplierConversation.phone_number.like(f"%{clean_phone_10}"))
        ).filter(
            SupplierConversation.conversation_status == "IN_PROGRESS"
        ).first()
        if active_conv and active_conv.collected_data:
            draft_name = active_conv.collected_data.get("company_name")
            if draft_name:
                company_name = f"{draft_name} (Registering...)"
                contact_person = "Registering Onboard"

    messages = db.query(WhatsAppInboxMessage).filter(
        WhatsAppInboxMessage.supplier_phone == phone_number
    ).order_by(WhatsAppInboxMessage.created_at.asc()).all()

    return {
        "supplier": {
            "id": supplier_id,
            "company_name": company_name,
            "contact_person": contact_person,
            "whatsapp_number": phone_number
        },
        "messages": [
            {
                "id": m.id,
                "message_text": m.message_text,
                "direction": m.direction,
                "is_read": m.is_read,
                "created_at": m.created_at.isoformat() if m.created_at else ""
            }
            for m in messages
        ]
    }


# ---------------------------------------------------------------------------
# POST /inbox/conversations/{phone_number}/mark-read
# Marks all inbound messages from a phone number as read
# ---------------------------------------------------------------------------
@router.post("/conversations/{phone_number}/mark-read")
def mark_read(phone_number: str, db: Session = Depends(get_db)):
    db.query(WhatsAppInboxMessage).filter(
        WhatsAppInboxMessage.supplier_phone == phone_number,
        WhatsAppInboxMessage.direction == "inbound",
        WhatsAppInboxMessage.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /inbox/conversations/{phone_number}/send
# PM sends a reply to a supplier phone number
# ---------------------------------------------------------------------------
class SendReplyRequest(BaseModel):
    message: str


@router.post("/conversations/{phone_number}/send")
def send_reply(
    phone_number: str,
    body: SendReplyRequest,
    db: Session = Depends(get_db)
):
    # Normalise phone number for Meta API (must be digits only, with country code)
    phone = phone_number.replace("+", "").strip()
    if phone.startswith("91") and len(phone) > 11:
        pass  # already has country code
    elif len(phone) == 10:
        phone = f"91{phone}"

    # Send via WhatsApp API
    # Note: send_text_message itself now automatically logs the outbound message
    # to the WhatsAppInboxMessage table, so we do not log it manually here.
    result = send_text_message(phone, body.message)

    return {"status": "sent", "whatsapp_response": result}
