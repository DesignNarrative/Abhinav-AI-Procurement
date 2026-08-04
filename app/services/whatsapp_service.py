import requests
import os

from app.config.settings import (
    META_ACCESS_TOKEN,
    META_PHONE_NUMBER_ID
)


def send_text_message(
    phone_number: str,
    message: str
):

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{META_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization":
            f"Bearer {META_ACCESS_TOKEN}",

        "Content-Type":
            "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",

        "to": phone_number,

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
    print("TO:", phone_number)
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
            clean_phone = phone_number.replace("+", "").strip()
            clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
            
            supplier = db.query(Supplier).filter(
                (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                (Supplier.whatsapp_number == phone_number)
            ).first()
            
            inbox_msg = WhatsAppInboxMessage(
                supplier_id=supplier.id if supplier else None,
                supplier_phone=phone_number,
                message_text=message,
                direction="outbound",
                is_read=True
            )
            db.add(inbox_msg)
            db.commit()
            print(f"[INBOX] Logged outbound message to {phone_number} successfully.")
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


def send_document_message(
    phone_number: str,
    file_path: str,
    filename: str,
    caption: str = None,
    mime_type: str = "application/pdf"
):
    """
    Upload a local document and send it to the recipient on WhatsApp.
    Reuses the same Graph API credentials as text sending.
    """
    media_id = upload_media(file_path, mime_type=mime_type)

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{META_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    document = {
        "id": media_id,
        "filename": filename
    }
    if caption:
        document["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "document",
        "document": document
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    return response.json()