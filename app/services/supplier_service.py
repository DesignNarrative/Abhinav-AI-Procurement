from sqlalchemy.orm import Session

from app.models.supplier import Supplier


class SupplierService:

    @staticmethod
    def get_dashboard_stats(
        db: Session
    ):

        total_suppliers = db.query(
            Supplier
        ).filter(
            Supplier.registration_status != "PENDING_REGISTRATION"
        ).count()

        approved_suppliers = db.query(
            Supplier
        ).filter(
            Supplier.registration_status == "APPROVED"
        ).count()

        pending_suppliers = db.query(
            Supplier
        ).filter(
            Supplier.registration_status == "PENDING"
        ).count()

        rejected_suppliers = db.query(
            Supplier
        ).filter(
            Supplier.registration_status == "REJECTED"
        ).count()

        recent_suppliers = db.query(
            Supplier
        ).filter(
            Supplier.registration_status != "PENDING_REGISTRATION"
        ).order_by(
            Supplier.created_at.desc()
        ).limit(10).all()

        return {
            "total_suppliers": total_suppliers,
            "approved_suppliers": approved_suppliers,
            "pending_suppliers": pending_suppliers,
            "rejected_suppliers": rejected_suppliers,
            "recent_suppliers": recent_suppliers
        }

    @staticmethod
    def get_supplier_by_id(
        db: Session,
        supplier_id: int
    ):

        return db.query(
            Supplier
        ).filter(
            Supplier.id == supplier_id
        ).first()