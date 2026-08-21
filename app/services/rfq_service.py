from datetime import datetime
from sqlalchemy.orm import Session

from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.supplier import Supplier


class RFQService:

    @staticmethod
    def _generate_rfq_number(db: Session) -> str:
        """Generate sequential RFQ number using Postgres sequence to avoid concurrency race conditions."""
        from sqlalchemy import text
        db.execute(text("CREATE SEQUENCE IF NOT EXISTS rfq_number_seq START 1;"))
        
        # Auto-align the sequence to the highest existing RFQ number if it is fresh
        seq_state = db.execute(text("SELECT last_value, is_called FROM rfq_number_seq")).first()
        if seq_state and seq_state[0] == 1 and not seq_state[1]:
            last = db.query(RFQ).order_by(RFQ.id.desc()).first()
            if last and last.rfq_number:
                try:
                    max_seq = int(last.rfq_number.split("-")[-1])
                    db.execute(text("SELECT setval('rfq_number_seq', :max_seq, true)"), {"max_seq": max_seq})
                except (ValueError, IndexError):
                    pass
                    
        year = datetime.now().year
        next_val = db.execute(text("SELECT nextval('rfq_number_seq')")).scalar()
        return f"RFQ-{year}-{next_val:03d}"

    # ──────────────────────────────────────────────────
    # RFQ CRUD
    # ──────────────────────────────────────────────────

    @staticmethod
    def create_rfq(db: Session, data: dict) -> RFQ:
        rfq = RFQ(
            rfq_number=RFQService._generate_rfq_number(db),
            project_name=data["project_name"],
            site_name=data["site_name"],
            delivery_location=data["delivery_location"],
            payment_terms=data.get("payment_terms"),
            created_by=data["created_by"],
            priority=data.get("priority"),
            required_date=data.get("required_date"),
            purpose=data.get("purpose"),
            status="Draft"
        )
        db.add(rfq)
        db.commit()
        db.refresh(rfq)
        return rfq

    @staticmethod
    def get_rfq(db: Session, rfq_id: int) -> RFQ:
        return db.query(RFQ).filter(RFQ.id == rfq_id).first()

    @staticmethod
    def list_rfqs(db: Session, status: str = None) -> list:
        query = db.query(RFQ)
        if status:
            query = query.filter(RFQ.status == status)
        return query.order_by(RFQ.created_at.desc()).all()

    @staticmethod
    def update_status(db: Session, rfq_id: int, status: str) -> RFQ:
        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if rfq:
            rfq.status = status
            db.commit()
            db.refresh(rfq)
        return rfq

    @staticmethod
    def update_rfq_details(
        db: Session,
        rfq_id: int,
        payment_terms: str = None
    ) -> RFQ:
        """Update RFQ-specific editable fields (currently payment terms).

        payment_terms uses the existing column; no schema change involved.
        Passing None leaves the value unchanged; passing "" clears it.
        """
        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if not rfq:
            return None
        if payment_terms is not None:
            rfq.payment_terms = payment_terms.strip() or None
        db.commit()
        db.refresh(rfq)
        return rfq

    # ──────────────────────────────────────────────────
    # Generate RFQ from an existing Requirement (snapshot)
    # ──────────────────────────────────────────────────

    @staticmethod
    def generate_rfq_from_requirement(db: Session, requirement_id: int) -> RFQ:
        """Create a Draft RFQ by snapshotting a Requirement + its materials.

        Enterprise snapshot model: values are COPIED once at generation time so
        that later edits to the Requirement never mutate an already-created RFQ.
        The whole operation is a single transaction — on any error nothing is
        persisted (no orphan RFQ).

        Returns None if the requirement does not exist.
        Raises ValueError if the requirement has no materials.
        """
        from app.models.requirement import Requirement
        from app.models.requirement_material import RequirementMaterial

        requirement = (
            db.query(Requirement)
            .filter(Requirement.id == requirement_id)
            .first()
        )
        if not requirement:
            return None

        materials = (
            db.query(RequirementMaterial)
            .filter(RequirementMaterial.requirement_id == requirement_id)
            .all()
        )
        if not materials:
            raise ValueError(
                "This requirement has no materials to generate an RFQ."
            )

        # Header delivery location: use the single common location if every
        # material shares one; otherwise leave blank for the Purchase Manager.
        locations = {
            m.delivery_location.strip()
            for m in materials
            if m.delivery_location and m.delivery_location.strip()
        }
        delivery_location = locations.pop() if len(locations) == 1 else ""

        try:
            rfq = RFQ(
                rfq_number=RFQService._generate_rfq_number(db),
                project_name=requirement.project_name,
                site_name=requirement.site_name,
                delivery_location=delivery_location,
                payment_terms=None,
                created_by=requirement.requested_by,
                priority=requirement.priority,
                required_date=(
                    requirement.required_date.isoformat()
                    if requirement.required_date else None
                ),
                purpose=requirement.purpose,
                status="Draft",
                requirement_id=requirement.id
            )
            db.add(rfq)
            db.flush()  # obtain rfq.id within the same transaction

            for m in materials:
                # Structured requirement fields that have no dedicated RFQ item
                # column are preserved inside the flexible dynamic_fields JSONB.
                dynamic = {}
                if m.specification:
                    dynamic["specification"] = m.specification
                if m.additional_requirements:
                    dynamic["additional_requirements"] = (
                        m.additional_requirements
                    )
                dynamic["alternate_brand_allowed"] = (
                    "Yes" if m.alternate_brand_allowed else "No"
                )

                item = RFQItem(
                    rfq_id=rfq.id,
                    # material_category is NOT NULL on rfq_items, but
                    # requirement category is optional — fall back to "General".
                    material_category=(m.category or "General"),
                    material_name=m.material_name,
                    quantity=m.quantity,
                    unit=m.unit,
                    brand_required=m.preferred_brand,
                    dynamic_fields=dynamic,
                    remarks=m.remarks
                )
                db.add(item)

            db.commit()
            db.refresh(rfq)
            return rfq

        except Exception:
            db.rollback()
            raise

    # ──────────────────────────────────────────────────
    # RFQ Items
    # ──────────────────────────────────────────────────

    @staticmethod
    def add_item(db: Session, rfq_id: int, data: dict) -> RFQItem:
        item = RFQItem(
            rfq_id=rfq_id,
            material_category=data["material_category"],
            material_name=data["material_name"],
            quantity=data["quantity"],
            unit=data["unit"],
            brand_required=data.get("brand_required"),
            dynamic_fields=data.get("dynamic_fields") or {},
            remarks=data.get("remarks")
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def get_items(db: Session, rfq_id: int) -> list:
        return db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()

    # ──────────────────────────────────────────────────
    # RFQ Vendors
    # ──────────────────────────────────────────────────

    @staticmethod
    def add_vendor(db: Session, rfq_id: int, vendor_id: int) -> RFQVendor:
        existing = (
            db.query(RFQVendor)
            .filter(
                RFQVendor.rfq_id == rfq_id,
                RFQVendor.vendor_id == vendor_id
            )
            .first()
        )
        if existing:
            return existing

        rv = RFQVendor(
            rfq_id=rfq_id,
            vendor_id=vendor_id
        )
        db.add(rv)
        db.commit()
        db.refresh(rv)
        return rv

    @staticmethod
    def get_vendors(db: Session, rfq_id: int) -> list:
        return (
            db.query(RFQVendor)
            .filter(RFQVendor.rfq_id == rfq_id)
            .all()
        )

    # ──────────────────────────────────────────────────
    # Send via WhatsApp
    # ──────────────────────────────────────────────────

    @staticmethod
    def send_rfq_to_vendors(
        db: Session,
        rfq_id: int,
        deadline: str = None,
        contact_person: str = None,
        contact_number: str = None,
        purchase_team_number: str = None
    ) -> dict:
        from app.services.rfq_whatsapp_service import generate_rfq_whatsapp_message
        from app.services.whatsapp_service import send_text_message

        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if not rfq:
            return {"error": "RFQ not found"}

        items = db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()
        rfq_vendors = (
            db.query(RFQVendor)
            .filter(RFQVendor.rfq_id == rfq_id)
            .all()
        )

        if not rfq_vendors:
            return {"error": "No vendors attached to this RFQ"}

        # Build item dicts
        item_dicts = [
            {
                "material_name": it.material_name,
                "material_category": it.material_category,
                "quantity": float(it.quantity),
                "unit": it.unit,
                "brand_required": it.brand_required,
                "dynamic_fields": it.dynamic_fields or {},
                "remarks": it.remarks
            }
            for it in items
        ]

        # Generate message once — same for all vendors
        message = generate_rfq_whatsapp_message(
            rfq_number=rfq.rfq_number,
            project_name=rfq.project_name,
            site_name=rfq.site_name,
            delivery_location=rfq.delivery_location,
            payment_terms=rfq.payment_terms,
            items=item_dicts,
            deadline=deadline,
            contact_person=contact_person,
            contact_number=contact_number,
            priority=rfq.priority,
            required_date=rfq.required_date,
            purpose=rfq.purpose,
            purchase_team_number=purchase_team_number
        )

        results = []
        for rv in rfq_vendors:
            vendor = db.query(Supplier).filter(Supplier.id == rv.vendor_id).first()
            if not vendor:
                continue

            phone = vendor.whatsapp_number
            # Normalize to international format
            if not phone.startswith("+"):
                phone = f"91{phone}" if len(phone) == 10 else phone

            # Check 24-hour customer window
            from datetime import timedelta, timezone
            from app.models.whatsapp_inbox_message import WhatsAppInboxMessage
            from app.services.whatsapp_service import send_template_message
            from app.config.settings import WHATSAPP_RFQ_TEMPLATE

            clean_phone_10 = phone[-10:]
            limit_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            
            last_inbound = db.query(WhatsAppInboxMessage).filter(
                (WhatsAppInboxMessage.supplier_phone.like(f"%{clean_phone_10}")) |
                (WhatsAppInboxMessage.supplier_phone == phone),
                WhatsAppInboxMessage.direction == "inbound",
                WhatsAppInboxMessage.created_at >= limit_24h
            ).first()

            if last_inbound:
                wa_result = send_text_message(phone, message)
                whatsapp_status = "Sent"

                # ── Send quotation trigger so supplier knows to type QUOTE ──
                from app.services.rfq_whatsapp_service import generate_quotation_trigger_message
                trigger_msg = generate_quotation_trigger_message(rfq.rfq_number)
                try:
                    send_text_message(phone, trigger_msg)
                except Exception as te:
                    print(f"[RFQ] Failed to send quotation trigger to {phone}: {te}")

                # ── Log both outbound messages to inbox so PM sees full flow ──
                try:
                    db.add(WhatsAppInboxMessage(
                        supplier_id=vendor.id,
                        supplier_phone=phone,
                        message_text=message,
                        direction="outbound",
                        is_read=True,
                        media_type="text"
                    ))
                    db.add(WhatsAppInboxMessage(
                        supplier_id=vendor.id,
                        supplier_phone=phone,
                        message_text=trigger_msg,
                        direction="outbound",
                        is_read=True,
                        media_type="text"
                    ))
                    db.commit()
                except Exception as le:
                    db.rollback()
                    print(f"[RFQ] Failed to log outbound RFQ messages to inbox: {le}")
            else:
                template_name = WHATSAPP_RFQ_TEMPLATE or "rfq_invitation"
                if template_name == "hello_world":
                    components = []
                else:
                    components = [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": vendor.company_name or "Supplier"},
                                {"type": "text", "text": rfq.rfq_number},
                                {"type": "text", "text": rfq.project_name}
                            ]
                        }
                    ]
                wa_result = send_template_message(
                    phone_number=phone,
                    template_name=template_name,
                    components=components
                )
                whatsapp_status = "Sent (Template)"

            rv.sent_at = datetime.now()
            rv.whatsapp_status = whatsapp_status
            db.commit()

            results.append({
                "vendor": vendor.company_name,
                "phone": phone,
                "result": wa_result
            })

        # Update RFQ status
        rfq.status = "Sent"
        db.commit()

        return {
            "rfq_number": rfq.rfq_number,
            "message_preview": message,
            "sent_to": results
        }

    @staticmethod
    def resend_rfq_to_specific_vendors(
        db: Session,
        rfq_id: int,
        vendor_ids: list,
        deadline: str = None,
        contact_person: str = None,
        contact_number: str = None,
        purchase_team_number: str = None
    ) -> dict:
        """
        Re-send (or first-send) the RFQ WhatsApp message to a specific subset
        of vendor IDs.  For each vendor_id:
        - If not yet attached to the RFQ, it is added first.
        - The message is then sent via WhatsApp.
        RFQ status is NOT changed (already Sent).
        """
        from app.services.rfq_whatsapp_service import generate_rfq_whatsapp_message
        from app.services.whatsapp_service import send_text_message

        rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
        if not rfq:
            return {"error": "RFQ not found"}

        if not vendor_ids:
            return {"error": "No vendor IDs provided"}

        items = db.query(RFQItem).filter(RFQItem.rfq_id == rfq_id).all()
        item_dicts = [
            {
                "material_name": it.material_name,
                "material_category": it.material_category,
                "quantity": float(it.quantity),
                "unit": it.unit,
                "brand_required": it.brand_required,
                "dynamic_fields": it.dynamic_fields or {},
                "remarks": it.remarks
            }
            for it in items
        ]

        # Generate message once — same for all vendors
        message = generate_rfq_whatsapp_message(
            rfq_number=rfq.rfq_number,
            project_name=rfq.project_name,
            site_name=rfq.site_name,
            delivery_location=rfq.delivery_location,
            payment_terms=rfq.payment_terms,
            items=item_dicts,
            deadline=deadline,
            contact_person=contact_person,
            contact_number=contact_number,
            priority=rfq.priority,
            required_date=rfq.required_date,
            purpose=rfq.purpose,
            purchase_team_number=purchase_team_number
        )

        results = []
        for vendor_id in vendor_ids:
            vendor = db.query(Supplier).filter(Supplier.id == vendor_id).first()
            if not vendor:
                results.append({"vendor_id": vendor_id, "error": "Vendor not found"})
                continue

            # Ensure vendor is attached to this RFQ (add if missing)
            existing = (
                db.query(RFQVendor)
                .filter(RFQVendor.rfq_id == rfq_id, RFQVendor.vendor_id == vendor_id)
                .first()
            )
            if not existing:
                existing = RFQVendor(rfq_id=rfq_id, vendor_id=vendor_id)
                db.add(existing)
                db.commit()
                db.refresh(existing)

            phone = vendor.whatsapp_number
            if not phone.startswith("+"):
                phone = f"91{phone}" if len(phone) == 10 else phone

            # Check 24-hour customer window
            from datetime import timedelta, timezone
            from app.models.whatsapp_inbox_message import WhatsAppInboxMessage
            from app.services.whatsapp_service import send_template_message
            from app.config.settings import WHATSAPP_RFQ_TEMPLATE

            clean_phone_10 = phone[-10:]
            limit_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            
            last_inbound = db.query(WhatsAppInboxMessage).filter(
                (WhatsAppInboxMessage.supplier_phone.like(f"%{clean_phone_10}")) |
                (WhatsAppInboxMessage.supplier_phone == phone),
                WhatsAppInboxMessage.direction == "inbound",
                WhatsAppInboxMessage.created_at >= limit_24h
            ).first()

            if last_inbound:
                wa_result = send_text_message(phone, message)
                whatsapp_status = "Sent"

                # ── Send quotation trigger so supplier knows to type QUOTE ──
                from app.services.rfq_whatsapp_service import generate_quotation_trigger_message
                trigger_msg = generate_quotation_trigger_message(rfq.rfq_number)
                try:
                    send_text_message(phone, trigger_msg)
                except Exception as te:
                    print(f"[RFQ] Failed to send quotation trigger to {phone}: {te}")

                # ── Log both outbound messages to inbox so PM sees full flow ──
                try:
                    db.add(WhatsAppInboxMessage(
                        supplier_id=vendor.id,
                        supplier_phone=phone,
                        message_text=message,
                        direction="outbound",
                        is_read=True,
                        media_type="text"
                    ))
                    db.add(WhatsAppInboxMessage(
                        supplier_id=vendor.id,
                        supplier_phone=phone,
                        message_text=trigger_msg,
                        direction="outbound",
                        is_read=True,
                        media_type="text"
                    ))
                    db.commit()
                except Exception as le:
                    db.rollback()
                    print(f"[RFQ] Failed to log outbound RFQ messages to inbox: {le}")
            else:
                template_name = WHATSAPP_RFQ_TEMPLATE or "rfq_invitation"
                if template_name == "hello_world":
                    components = []
                else:
                    components = [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": vendor.company_name or "Supplier"},
                                {"type": "text", "text": rfq.rfq_number},
                                {"type": "text", "text": rfq.project_name}
                            ]
                        }
                    ]
                wa_result = send_template_message(
                    phone_number=phone,
                    template_name=template_name,
                    components=components
                )
                whatsapp_status = "Sent (Template)"

            existing.sent_at = datetime.now()
            existing.whatsapp_status = whatsapp_status
            db.commit()

            results.append({
                "vendor": vendor.company_name,
                "phone": phone,
                "result": wa_result
            })

        return {
            "rfq_number": rfq.rfq_number,
            "sent_to": results
        }


