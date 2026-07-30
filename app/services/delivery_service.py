from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime

from app.models.delivery import Delivery
from app.models.delivery_item import DeliveryItem
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier import Supplier  # noqa: F401

# Resolve mappers when used standalone.
from app.models.rfq import RFQ  # noqa: F401
from app.models.rfq_vendor import RFQVendor  # noqa: F401
from app.models.requirement import Requirement  # noqa: F401


VALID_STATUSES = [
    "Dispatched", "In Transit", "Delivered", "Partially Delivered",
    "Short Supply", "Damaged", "Rejected", "Replacement"
]


class DeliveryService:

    # =====================================================
    # Create a delivery (dispatch) record for a PO
    # =====================================================

    @staticmethod
    def create_delivery(db: Session, po_id: int, data: dict) -> Delivery:
        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == po_id
        ).first()
        if not po:
            raise ValueError("Purchase Order not found")

        status = data.get("status", "Dispatched")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid delivery status: {status}")

        delivery = Delivery(
            po_id=po_id,
            dispatch_date=data.get("dispatch_date"),
            eta=data.get("eta"),
            vehicle_number=data.get("vehicle_number"),
            driver_name=data.get("driver_name"),
            driver_number=data.get("driver_number"),
            lr_copy_path=data.get("lr_copy_path"),
            status=status,
            remarks=data.get("remarks"),
            created_by=data["created_by"]
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        return delivery

    # =====================================================
    # Record GRN (site engineer confirmation) for a delivery
    # =====================================================

    @staticmethod
    def record_grn(
        db: Session,
        delivery_id: int,
        confirmed_by: str,
        items: list
    ) -> Delivery:
        """
        `items` is a list of dicts:
          {po_item_id, received_quantity, quality_ok, damage_notes, photo_path}
        Recording GRN replaces existing GRN lines for this delivery so a
        correction re-submits the full set (delivery record itself is kept).
        """
        delivery = db.query(Delivery).filter(
            Delivery.id == delivery_id
        ).first()
        if not delivery:
            raise ValueError("Delivery not found")

        po_item_ids = {
            pi.id for pi in db.query(PurchaseOrderItem).filter(
                PurchaseOrderItem.po_id == delivery.po_id
            ).all()
        }

        # Clear previous GRN lines for this delivery (idempotent re-submit)
        db.query(DeliveryItem).filter(
            DeliveryItem.delivery_id == delivery_id
        ).delete()

        any_damage = False
        for row in items:
            po_item_id = row.get("po_item_id")
            if po_item_id not in po_item_ids:
                raise ValueError(
                    f"PO item {po_item_id} does not belong to this PO"
                )
            quality_ok = bool(row.get("quality_ok", True))
            if not quality_ok:
                any_damage = True

            db.add(DeliveryItem(
                delivery_id=delivery_id,
                po_item_id=po_item_id,
                received_quantity=row.get("received_quantity", 0) or 0,
                quality_ok=quality_ok,
                damage_notes=row.get("damage_notes"),
                photo_path=row.get("photo_path")
            ))

        delivery.confirmed_by = confirmed_by
        delivery.confirmed_at = datetime.now()

        # Set delivery status based on this delivery vs PO fully received.
        fully = DeliveryService._is_po_fully_received(
            db, delivery.po_id, include_uncommitted=True
        )
        if any_damage:
            delivery.status = "Damaged"
        elif fully:
            delivery.status = "Delivered"
        else:
            delivery.status = "Partially Delivered"

        db.flush()

        # Auto-close the PO when every item is fully received.
        if DeliveryService._is_po_fully_received(db, delivery.po_id):
            po = db.query(PurchaseOrder).filter(
                PurchaseOrder.id == delivery.po_id
            ).first()
            if po and po.status not in ("Cancelled",):
                po.status = "Closed"

        db.commit()
        db.refresh(delivery)
        return delivery

    # =====================================================
    # Received-vs-ordered summary per PO item
    # =====================================================

    @staticmethod
    def get_po_receipt_summary(db: Session, po_id: int) -> list:
        po_items = db.query(PurchaseOrderItem).filter(
            PurchaseOrderItem.po_id == po_id
        ).order_by(PurchaseOrderItem.id.asc()).all()

        summary = []
        for pi in po_items:
            received = db.query(
                func.coalesce(func.sum(DeliveryItem.received_quantity), 0)
            ).filter(
                DeliveryItem.po_item_id == pi.id
            ).scalar() or 0

            ordered = float(pi.ordered_quantity or 0)
            received = float(received)
            summary.append({
                "po_item_id": pi.id,
                "material_name": pi.material_name,
                "unit": pi.unit,
                "ordered_quantity": ordered,
                "received_quantity": received,
                "pending_quantity": round(max(ordered - received, 0), 3),
                "fully_received": received >= ordered and ordered > 0
            })
        return summary

    @staticmethod
    def _is_po_fully_received(
        db: Session,
        po_id: int,
        include_uncommitted: bool = False
    ) -> bool:
        if include_uncommitted:
            db.flush()
        summary = DeliveryService.get_po_receipt_summary(db, po_id)
        if not summary:
            return False
        return all(row["fully_received"] for row in summary)

    # =====================================================
    # Queries
    # =====================================================

    @staticmethod
    def list_deliveries(db: Session, po_id: int) -> list:
        deliveries = db.query(Delivery).filter(
            Delivery.po_id == po_id
        ).order_by(Delivery.created_at.asc()).all()

        result = []
        for d in deliveries:
            result.append({
                "id": d.id,
                "po_id": d.po_id,
                "dispatch_date": (
                    d.dispatch_date.isoformat() if d.dispatch_date else None
                ),
                "eta": d.eta.isoformat() if d.eta else None,
                "vehicle_number": d.vehicle_number,
                "driver_name": d.driver_name,
                "driver_number": d.driver_number,
                "lr_copy_path": d.lr_copy_path,
                "status": d.status,
                "confirmed_by": d.confirmed_by,
                "confirmed_at": (
                    d.confirmed_at.isoformat() if d.confirmed_at else None
                ),
                "remarks": d.remarks,
                "created_by": d.created_by,
                "created_at": d.created_at.isoformat(),
                "items": [
                    {
                        "id": it.id,
                        "po_item_id": it.po_item_id,
                        "material_name": (
                            it.po_item.material_name if it.po_item else None
                        ),
                        "received_quantity": float(it.received_quantity or 0),
                        "quality_ok": it.quality_ok,
                        "damage_notes": it.damage_notes,
                        "photo_path": it.photo_path
                    }
                    for it in d.items
                ]
            })
        return result

    @staticmethod
    def get_delivery(db: Session, delivery_id: int) -> Delivery:
        return db.query(Delivery).filter(
            Delivery.id == delivery_id
        ).first()
