import requests
import os

from app.config.settings import (
    META_ACCESS_TOKEN,
    META_PHONE_NUMBER_ID
)


def normalize_phone_number(phone: str) -> str:
    """Normalize phone number to digits only. Prepend 91 for Indian 10-digit numbers."""
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"91{digits}"
    return digits


def send_text_message(
    phone_number: str,
    message: str
):
    normalized_phone = normalize_phone_number(phone_number)

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{META_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": normalized_phone,
        "type": "text",
        "text": {
            "body": message
        }
    }

    # DEBUG INFORMATION
    print("\n========== WHATSAPP SEND DEBUG ==========")
    print("URL:", url)
    print("PHONE NUMBER ID:", META_PHONE_NUMBER_ID)
    print("TOKEN PREFIX:", META_ACCESS_TOKEN[:20])
    print("TO (NORMALIZED):", normalized_phone)
    try:
        print("PAYLOAD:", payload)
    except UnicodeEncodeError:
        print("PAYLOAD:", str(payload).encode("ascii", "ignore").decode("ascii"))
    print("=========================================\n")

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    print("STATUS:", response.status_code)
    try:
        print("RESPONSE:", response.text)
    except UnicodeEncodeError:
        print("RESPONSE:", response.text.encode("ascii", "ignore").decode("ascii"))

    # Log outbound message to inbox DB
    try:
        from app.database.database import SessionLocal
        from app.models.supplier import Supplier
        from app.models.whatsapp_inbox_message import WhatsAppInboxMessage
        
        db = SessionLocal()
        try:
            clean_phone_10 = normalized_phone[-10:]
            supplier = db.query(Supplier).filter(
                (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                (Supplier.whatsapp_number == normalized_phone)
            ).first()
            
            resp_data = response.json()
            msg_id = resp_data.get("messages", [{}])[0].get("id") if "messages" in resp_data else None

            inbox_msg = WhatsAppInboxMessage(
                supplier_id=supplier.id if supplier else None,
                supplier_phone=normalized_phone,
                message_text=message,
                direction="outbound",
                is_read=True,
                media_type="text",
                whatsapp_message_id=msg_id
            )
            db.add(inbox_msg)
            db.commit()
            print(f"[INBOX] Logged outbound message to {normalized_phone} successfully.")
        except Exception as e:
            db.rollback()
            print(f"[INBOX] Failed to log outbound message: {e}")
        finally:
            db.close()
    except Exception as outer_e:
        print(f"[INBOX] Outer exception logging outbound message: {outer_e}")

    return response.json()


def upload_media(
    file_path: str,
    mime_type: str = "application/pdf"
):
    """
    Upload a local file to WhatsApp media storage and return its media id.
    Required before a document/image can be sent to a recipient.
    """
    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{META_PHONE_NUMBER_ID}/media"
    )

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}"
    }

    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, mime_type)
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type
        }
        response = requests.post(
            url,
            headers=headers,
            data=data,
            files=files
        )

    response.raise_for_status()
    return response.json().get("id")


def send_media_message(
    phone_number: str,
    file_path: str,
    filename: str,
    media_type: str,  # "image", "video", "document"
    mime_type: str,
    caption: str = None
):
    """Upload media locally and send it to recipient via Meta Graph API."""
    normalized_phone = normalize_phone_number(phone_number)
    media_id = upload_media(file_path, mime_type=mime_type)

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{META_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Format payload based on WhatsApp media type rules
    if media_type == "image":
        media_obj = {"id": media_id}
        if caption:
            media_obj["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized_phone,
            "type": "image",
            "image": media_obj
        }
    elif media_type == "video":
        media_obj = {"id": media_id}
        if caption:
            media_obj["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized_phone,
            "type": "video",
            "video": media_obj
        }
    else:  # Document (PDF, Excel, Zip, Word, PPT)
        doc_obj = {"id": media_id, "filename": filename}
        if caption:
            doc_obj["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized_phone,
            "type": "document",
            "document": doc_obj
        }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    # Log outbound media to inbox DB
    try:
        from app.database.database import SessionLocal
        from app.models.supplier import Supplier
        from app.models.whatsapp_inbox_message import WhatsAppInboxMessage
        
        db = SessionLocal()
        try:
            clean_phone_10 = normalized_phone[-10:]
            supplier = db.query(Supplier).filter(
                (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                (Supplier.whatsapp_number == normalized_phone)
            ).first()
            
            resp_data = response.json()
            msg_id = resp_data.get("messages", [{}])[0].get("id") if "messages" in resp_data else None

            # Local link url path (served via /uploads FastAPI mount)
            rel_path = f"uploads/media/{filename}"

            inbox_msg = WhatsAppInboxMessage(
                supplier_id=supplier.id if supplier else None,
                supplier_phone=normalized_phone,
                message_text=f"Sent file: {filename}",
                direction="outbound",
                is_read=True,
                media_type=media_type,
                media_path=rel_path,
                whatsapp_message_id=msg_id
            )
            db.add(inbox_msg)
            db.commit()
            print(f"[INBOX] Logged outbound media message successfully.")
        except Exception as e:
            db.rollback()
            print(f"[INBOX] Failed to log outbound media message: {e}")
        finally:
            db.close()
    except Exception as outer_e:
        print(f"[INBOX] Outer exception logging media: {outer_e}")

    return response.json()


def send_document_message(
    phone_number: str,
    file_path: str,
    filename: str,
    caption: str = None,
    mime_type: str = "application/pdf"
):
    """Backwards compatible document message wrapper."""
    return send_media_message(
        phone_number=phone_number,
        file_path=file_path,
        filename=filename,
        media_type="document",
        mime_type=mime_type,
        caption=caption
    )