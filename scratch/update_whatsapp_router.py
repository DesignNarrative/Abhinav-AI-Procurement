import os

file_path = r"app/api/whatsapp.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add import
old_import = 'from app.models.supplier import Supplier'
new_import = 'from app.models.supplier import Supplier\nfrom app.models.whatsapp_inbox_message import WhatsAppInboxMessage'

if old_import in content:
    content = content.replace(old_import, new_import)
    print("Import statement updated.")
else:
    print("Import statement already updated or not found.")

# 2. Update text routing block
old_text_block = """                incoming = (message_text or "").strip().upper()
                registration_keywords = ["HI", "HELLO", "HII", "START"]

                routed_to_quotation = False

                if not active_conversation and incoming not in registration_keywords:
                    # Check if sender is an approved supplier
                    clean_phone = sender_phone.replace("+", "").strip()
                    clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
                    supplier = db.query(Supplier).filter(
                        (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                        (Supplier.whatsapp_number == sender_phone)
                    ).filter(
                        Supplier.registration_status == "APPROVED"
                    ).first()

                    # Only treat substantial messages that look like a quote as
                    # quotations — greetings/short replies fall through to the
                    # normal registration handler.
                    text_lower = (message_text or "").lower()
                    quotation_signals = [
                        "quotation", "quote", "rate", "price", "amount",
                        "gst", "\\u20b9", "rs", "per ", "qty", "nos"
                    ]
                    looks_like_quotation = any(sig in text_lower for sig in quotation_signals)

                    if supplier and looks_like_quotation:
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

                if not routed_to_quotation:
                    response = process_whatsapp_message(
                        sender_phone,
                        message_text,
                        db
                    )

                    send_text_message(
                        sender_phone,
                        response["reply"]
                    )"""

new_text_block = """                # Log inbound message to inbox DB (for all numbers - approved or registering)
                clean_phone = sender_phone.replace("+", "").strip()
                clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
                supplier = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == sender_phone)
                ).first()

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=sender_phone,
                        message_text=message_text,
                        direction="inbound",
                        is_read=False
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound text from {sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log inbound text: {e}")

                incoming = (message_text or "").strip().upper()
                registration_keywords = ["HI", "HELLO", "HII", "START"]

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
                        "gst", "\\u20b9", "rs", "per ", "qty", "nos"
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
                        # Approved supplier chatting casually - bot stays silent.
                        # (Already logged to inbox DB above)
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
                    )"""

# Normalise spacing of raw raw strings to match git formatting
old_text_block_raw = old_text_block.replace("\r\n", "\n")
new_text_block_raw = new_text_block.replace("\r\n", "\n")
content_raw = content.replace("\r\n", "\n")

if old_text_block_raw in content_raw:
    content_raw = content_raw.replace(old_text_block_raw, new_text_block_raw)
    print("Text routing block updated.")
else:
    print("Text routing block not found or already updated.")

# 3. Update document block
old_doc_block = """            elif message.get("type") == "document":

                print("DOCUMENT RECEIVED")

                document = message["document"]"""

new_doc_block = """            elif message.get("type") == "document":

                print("DOCUMENT RECEIVED")

                document = message["document"]
                filename = document.get("filename", "document.pdf")

                # Log inbound document to inbox DB
                clean_phone = sender_phone.replace("+", "").strip()
                clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
                supplier = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == sender_phone)
                ).first()

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=sender_phone,
                        message_text=f"[Document: {filename}]",
                        direction="inbound",
                        is_read=False
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound document from {sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log document: {e}")"""

old_doc_block_raw = old_doc_block.replace("\r\n", "\n")
new_doc_block_raw = new_doc_block.replace("\r\n", "\n")

if old_doc_block_raw in content_raw:
    content_raw = content_raw.replace(old_doc_block_raw, new_doc_block_raw)
    print("Document block updated.")
else:
    print("Document block not found or already updated.")

# 4. Update image block
old_img_block = """            elif message.get("type") == "image":

                print("IMAGE RECEIVED")

                image = message["image"]"""

new_img_block = """            elif message.get("type") == "image":

                print("IMAGE RECEIVED")

                image = message["image"]

                # Log inbound image to inbox DB
                clean_phone = sender_phone.replace("+", "").strip()
                clean_phone_10 = clean_phone[-10:] if (clean_phone.startswith("91") and len(clean_phone) > 10) else clean_phone
                supplier = db.query(Supplier).filter(
                    (Supplier.whatsapp_number.like(f"%{clean_phone_10}")) |
                    (Supplier.whatsapp_number == sender_phone)
                ).first()

                try:
                    inbox_msg = WhatsAppInboxMessage(
                        supplier_id=supplier.id if supplier else None,
                        supplier_phone=sender_phone,
                        message_text="[Image]",
                        direction="inbound",
                        is_read=False
                    )
                    db.add(inbox_msg)
                    db.commit()
                    print(f"[INBOX] Logged inbound image from {sender_phone} successfully.")
                except Exception as e:
                    db.rollback()
                    print(f"[INBOX] Failed to log image: {e}")"""

old_img_block_raw = old_img_block.replace("\r\n", "\n")
new_img_block_raw = new_img_block.replace("\r\n", "\n")

if old_img_block_raw in content_raw:
    content_raw = content_raw.replace(old_img_block_raw, new_img_block_raw)
    print("Image block updated.")
else:
    print("Image block not found or already updated.")

# Write back
with open(file_path, "w", encoding="utf-8") as f:
    f.write(content_raw)
print("File update complete.")
