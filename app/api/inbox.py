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
    from app.services.whatsapp_service import normalize_phone_number
    normalized_phone = normalize_phone_number(phone_number)
    clean_phone_10 = normalized_phone[-10:]
    
    supplier = db.query(Supplier).filter(
        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
        (Supplier.whatsapp_number == normalized_phone)
    ).first()

    company_name = f"New Supplier (+{normalized_phone})"
    contact_person = "Unregistered"
    supplier_id = None

    if supplier:
        company_name = supplier.company_name
        contact_person = supplier.contact_person_name or "Approved"
        supplier_id = supplier.id
    else:
        active_conv = db.query(SupplierConversation).filter(
            (SupplierConversation.phone_number == normalized_phone) |
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
        WhatsAppInboxMessage.supplier_phone == normalized_phone
    ).order_by(WhatsAppInboxMessage.created_at.asc()).all()

    return {
        "supplier": {
            "id": supplier_id,
            "company_name": company_name,
            "contact_person": contact_person,
            "whatsapp_number": normalized_phone
        },
        "messages": [
            {
                "id": m.id,
                "message_text": m.message_text,
                "direction": m.direction,
                "is_read": m.is_read,
                "media_type": m.media_type,
                "media_path": m.media_path,
                "is_deleted_for_me": m.is_deleted_for_me,
                "is_deleted_for_everyone": m.is_deleted_for_everyone,
                "is_edited": m.is_edited,
                "created_at": m.created_at.isoformat() if m.created_at else ""
            }
            for m in messages if not m.is_deleted_for_me
        ]
    }


# ---------------------------------------------------------------------------
# POST /inbox/conversations/{phone_number}/mark-read
# Marks all inbound messages from a phone number as read
# ---------------------------------------------------------------------------
@router.post("/conversations/{phone_number}/mark-read")
def mark_read(phone_number: str, db: Session = Depends(get_db)):
    from app.services.whatsapp_service import normalize_phone_number
    normalized_phone = normalize_phone_number(phone_number)
    db.query(WhatsAppInboxMessage).filter(
        WhatsAppInboxMessage.supplier_phone == normalized_phone,
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
    from app.services.whatsapp_service import normalize_phone_number, send_text_message
    normalized_phone = normalize_phone_number(phone_number)

    # Send via WhatsApp API
    result = send_text_message(normalized_phone, body.message)

    return {"status": "sent", "whatsapp_response": result}


# ---------------------------------------------------------------------------
# POST /inbox/conversations/{phone_number}/send-media
# Upload and send media files (images, videos, PDFs, Excel, ZIP)
# ---------------------------------------------------------------------------
from fastapi import UploadFile, File
import shutil
import os

@router.post("/conversations/{phone_number}/send-media")
def send_media(
    phone_number: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    from app.services.whatsapp_service import normalize_phone_number, send_media_message
    normalized_phone = normalize_phone_number(phone_number)

    # Save the file locally in uploads/media (served via /uploads FastAPI mount)
    upload_dir = "uploads/media"
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Detect media type from extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif"):
        media_type = "image"
        mime_type = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext[1:]}"
    elif ext in (".mp4", ".mov", ".avi", ".3gp"):
        media_type = "video"
        mime_type = f"video/{ext[1:]}"
    else:
        media_type = "document"
        if ext == ".pdf":
            mime_type = "application/pdf"
        elif ext == ".xlsx":
            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif ext == ".zip":
            mime_type = "application/zip"
        else:
            mime_type = "application/octet-stream"

    # Send via WhatsApp API
    result = send_media_message(
        phone_number=normalized_phone,
        file_path=file_path,
        filename=file.filename,
        media_type=media_type,
        mime_type=mime_type
    )

    return {"status": "sent", "media_type": media_type, "whatsapp_response": result}


# ---------------------------------------------------------------------------
# Message edits and deletions endpoints
# ---------------------------------------------------------------------------
class EditMessageRequest(BaseModel):
    message_text: str


@router.post("/messages/{msg_id}/delete-for-me")
def delete_for_me(msg_id: int, db: Session = Depends(get_db)):
    msg = db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.id == msg_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.is_deleted_for_me = True
    db.commit()
    return {"status": "ok"}


@router.post("/messages/{msg_id}/delete-for-everyone")
def delete_for_everyone(msg_id: int, db: Session = Depends(get_db)):
    msg = db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.id == msg_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.is_deleted_for_everyone = True
    msg.message_text = "🚫 This message was deleted"
    db.commit()
    return {"status": "ok"}


@router.post("/messages/{msg_id}/edit")
def edit_message(msg_id: int, body: EditMessageRequest, db: Session = Depends(get_db)):
    msg = db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.id == msg_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.message_text = body.message_text
    msg.is_edited = True
    db.commit()
    return {"status": "ok"}

