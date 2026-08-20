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

    # Map raw mime-type to broad WhatsApp media categories
    media_category = "document"
    m_type_lower = mime_type.lower()
    if m_type_lower.startswith("image/"):
        media_category = "image"
    elif m_type_lower.startswith("video/"):
        media_category = "video"
    elif m_type_lower.startswith("audio/"):
        media_category = "audio"
    elif "sticker" in m_type_lower:
        media_category = "sticker"

    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, mime_type)
        }
        data = {
            "messaging_product": "whatsapp",
            "type": media_category
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
    caption: str = None,
    db_msg_id: int = None
):
    """Upload media locally and send it to recipient via Meta Graph API."""
    normalized_phone = normalize_phone_number(phone_number)

    media_id = None
    msg_id = None
    send_success = False

    try:
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
        if response.status_code in (200, 201):
            resp_data = response.json()
            msg_id = resp_data.get("messages", [{}])[0].get("id") if "messages" in resp_data else None
            send_success = True
        else:
            print(f"[WHATSAPP] Meta API returned status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[WHATSAPP] Failed to send media via Meta API: {e}")

    # Log outbound media to inbox DB (always logs/updates so it is visible in the local chat log)
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
            
            # Local link url path (served via /uploads FastAPI mount)
            rel_path = f"uploads/media/{filename}"

            if db_msg_id:
                # Update existing message (resolves duplicate logging)
                inbox_msg = db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.id == db_msg_id).first()
                if inbox_msg:
                    inbox_msg.whatsapp_message_id = msg_id
                    inbox_msg.delivery_status = "sent" if send_success else "failed"
                    if not send_success:
                        inbox_msg.message_text = f"⚠️ Failed to send: {filename}. Note: images must be <5MB, videos <16MB, and the recipient must have messaged the bot in the last 24 hours."
                    db.commit()
                    print(f"[INBOX] Updated existing outbound media message ID {db_msg_id} (Meta status: {inbox_msg.delivery_status}).")
            else:
                # Create a new log (e.g. for automatic triggers)
                inbox_msg = WhatsAppInboxMessage(
                    supplier_id=supplier.id if supplier else None,
                    supplier_phone=normalized_phone,
                    message_text=f"Sent file: {filename}",
                    direction="outbound",
                    is_read=True,
                    media_type=media_type,
                    media_path=rel_path,
                    whatsapp_message_id=msg_id,
                    delivery_status="sent" if send_success else "failed"
                )
                if not send_success:
                    inbox_msg.message_text = f"⚠️ Failed to send: {filename}. Note: images must be <5MB, videos <16MB, and the recipient must have messaged the bot in the last 24 hours."
                db.add(inbox_msg)
                db.commit()
                print(f"[INBOX] Logged new outbound media message successfully.")
        except Exception as e:
            db.rollback()
            print(f"[INBOX] Failed to log/update outbound media message: {e}")
        finally:
            db.close()
    except Exception as outer_e:
        print(f"[INBOX] Outer exception logging media: {outer_e}")

    return {
        "messages": [{"id": msg_id}] if msg_id else [],
        "local_logged": True,
        "whatsapp_sent": send_success
    }


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


def send_template_message(
    phone_number: str,
    template_name: str,
    language_code: str = "en_US",
    components: list = None
) -> dict:
    """Send a pre-approved template message to recipient via Meta Graph API."""
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
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code
            }
        }
    }

    if components:
        payload["template"]["components"] = components

    # DEBUG INFORMATION
    print("\n========== WHATSAPP TEMPLATE SEND DEBUG ==========")
    print("URL:", url)
    print("TO:", normalized_phone)
    print("TEMPLATE:", template_name)
    print("PAYLOAD:", payload)
    print("==================================================\n")

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)

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

            # Render a friendly text summary for the PM to read in the dashboard
            summary = f"[Template Invitation: {template_name}]"
            if components and len(components) > 0:
                params = components[0].get("parameters", [])
                if len(params) >= 3:
                    summary = f"Hello {params[0]['text']}! We have generated a new RFQ {params[1]['text']} for {params[2]['text']}. Please reply to this message to see the materials and submit rates."

            inbox_msg = WhatsAppInboxMessage(
                supplier_id=supplier.id if supplier else None,
                supplier_phone=normalized_phone,
                message_text=summary,
                direction="outbound",
                is_read=True,
                media_type="text",
                whatsapp_message_id=msg_id
            )
            db.add(inbox_msg)
            db.commit()
            print(f"[INBOX] Logged outbound template message successfully.")
        except Exception as e:
            db.rollback()
            print(f"[INBOX] Failed to log outbound template message: {e}")
        finally:
            db.close()
    except Exception as outer_e:
        print(f"[INBOX] Outer exception logging template: {outer_e}")

    return response.json()