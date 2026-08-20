from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date

from app.database.dependencies import get_db
from app.models.supplier import Supplier

from app.schemas.supplier import (
    SupplierCreate,
    SupplierResponse,
    SupplierListResponse,
    SupplierApprovalRequest,
    SupplierRejectionRequest,
    SupplierUpdate
)

router = APIRouter(
    prefix="/suppliers",
    tags=["Suppliers"]
)

def generate_next_supplier_code(db: Session) -> str:
    try:
        next_val = db.execute(text("SELECT nextval('supplier_code_seq')")).scalar()
        return f"VEND{next_val:06d}"
    except Exception:
        try:
            max_code_row = db.execute(text(
                "SELECT max(supplier_code) FROM suppliers WHERE supplier_code LIKE 'VEND%'"
            )).scalar()
            if max_code_row:
                num_part = max_code_row.replace("VEND", "")
                next_val = int(num_part) + 1
            else:
                next_val = 1
            return f"VEND{next_val:06d}"
        except Exception:
            return "VEND000001"


@router.get("/")
def get_suppliers(db: Session = Depends(get_db)):
    return db.query(Supplier).filter(Supplier.registration_status != "PENDING_REGISTRATION").all()


@router.get(
    "/pending",
    response_model=list[SupplierListResponse]
)
def get_pending_suppliers(
    db: Session = Depends(get_db)
):
    return db.query(Supplier).filter(
        Supplier.registration_status == "PENDING"
    ).all()



@router.get("/approved")
def get_approved_suppliers(db: Session = Depends(get_db)):
    """Return all APPROVED suppliers as JSON for vendor selection dropdowns."""
    suppliers = db.query(Supplier).filter(
        Supplier.registration_status == "APPROVED"
    ).order_by(Supplier.company_name).all()
    return [
        {
            "id": s.id,
            "company_name": s.company_name,
            "supplier_category": s.supplier_category,
            "whatsapp_number": s.whatsapp_number
        }
        for s in suppliers
    ]


@router.get("/stats")
def get_supplier_stats(
    db: Session = Depends(get_db)
):

    total_suppliers = db.query(
        Supplier
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

    return {
        "total_suppliers": total_suppliers,
        "approved_suppliers": approved_suppliers,
        "pending_suppliers": pending_suppliers,
        "rejected_suppliers": rejected_suppliers
    }

@router.get("/dashboard")
def get_supplier_dashboard(
    db: Session = Depends(get_db)
):

    total_suppliers = db.query(
        Supplier
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

    today_registrations = db.query(
        Supplier
    ).filter(
        Supplier.created_at >= date.today()
    ).count()

    return {
        "total_suppliers": total_suppliers,
        "approved_suppliers": approved_suppliers,
        "pending_suppliers": pending_suppliers,
        "rejected_suppliers": rejected_suppliers,
        "today_registrations": today_registrations
    }

  
@router.get(
    "/recent",
    response_model=list[SupplierListResponse]
)
def get_recent_suppliers(
    db: Session = Depends(get_db)
):

    suppliers = db.query(
        Supplier
    ).order_by(
        Supplier.created_at.desc()
    ).limit(10).all()

    return suppliers  

@router.get(
    "/search",
    response_model=list[SupplierListResponse]
)
def search_suppliers(
    name: str,
    db: Session = Depends(get_db)
):

    suppliers = db.query(
        Supplier
    ).filter(
        Supplier.company_name.ilike(
            f"%{name}%"
        )
    ).all()

    return suppliers

@router.get(
    "/category/{category}",
    response_model=list[SupplierListResponse]
)
def get_suppliers_by_category(
    category: str,
    db: Session = Depends(get_db)
):

    suppliers = db.query(
        Supplier
    ).filter(
        Supplier.supplier_category.ilike(
            category
        )
    ).all()

    return suppliers


@router.get(
    "/approved",
    response_model=list[SupplierListResponse]
)
def get_approved_suppliers(
    db: Session = Depends(get_db)
):
    return db.query(Supplier).filter(
        Supplier.registration_status == "APPROVED"
    ).order_by(Supplier.company_name).all()
    
    
@router.get(
    "/rejected",
    response_model=list[SupplierListResponse]
)
def get_rejected_suppliers(
    db: Session = Depends(get_db)
):
    return db.query(Supplier).filter(
        Supplier.registration_status == "REJECTED"
    ).all()


@router.get(
    "/{supplier_id}",
    response_model=SupplierResponse
)
def get_supplier(
    supplier_id: int,
    db: Session = Depends(get_db)
):
    supplier = db.query(Supplier).filter(
        Supplier.id == supplier_id
    ).first()

    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found"
        )

    return supplier


@router.get(
    "/{supplier_id}/documents"
)
def get_supplier_documents(
    supplier_id: int,
    db: Session = Depends(get_db)
):

    supplier = db.query(
        Supplier
    ).filter(
        Supplier.id == supplier_id
    ).first()

    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found"
        )

    return {
        "supplier_id": supplier.id,
        "company_name": supplier.company_name,
        "gst_certificate_path":
            supplier.gst_certificate_path,
        "msme_certificate_path":
            supplier.msme_certificate_path
    }

@router.post("/register")
def register_supplier(
    supplier: SupplierCreate,
    db: Session = Depends(get_db)
):

    existing_gst = db.query(Supplier).filter(
        Supplier.gst_number == supplier.gst_number
    ).first()

    if existing_gst:
        raise HTTPException(
            status_code=400,
            detail="GST Number already registered"
        )


    new_supplier = Supplier(
        company_name=supplier.company_name,
        principal_business=supplier.principal_business,

        gst_number=supplier.gst_number,

        registered_address=supplier.registered_address,

        contact_person_name=supplier.contact_person_name,
        contact_person_email=supplier.contact_person_email,

        whatsapp_number=supplier.whatsapp_number,

        supplier_category=supplier.supplier_category,
        material_types=supplier.material_types,

        bank_name=supplier.bank_name,
        beneficiary_name=supplier.beneficiary_name,
        bank_account_number=supplier.bank_account_number,
        bank_ifsc=supplier.bank_ifsc,
        branch_name=supplier.branch_name,

        is_msme=supplier.is_msme,
        msme_number=supplier.msme_number,
        msme_certificate_path=supplier.msme_certificate_path,

        gst_certificate_path=supplier.gst_certificate_path,

        references=supplier.references,

        authorized_person_name=supplier.authorized_person_name,
        designation=supplier.designation,

        declaration_accepted=supplier.declaration_accepted
    )

    db.add(new_supplier)
    db.commit()
    db.refresh(new_supplier)

    return {
        "message": "Supplier Registered Successfully",
        "supplier_id": new_supplier.id
    }


@router.post("/manual")
def register_supplier_manual(
    supplier: SupplierCreate,
    db: Session = Depends(get_db)
):
    """
    Manually register a supplier from the dashboard.
    Automatically assigns a vendor code and marks them as APPROVED.
    """
    if supplier.gst_number:
        existing_gst = db.query(Supplier).filter(
            Supplier.gst_number == supplier.gst_number
        ).first()
        if existing_gst:
            raise HTTPException(
                status_code=400,
                detail="GST Number already registered"
            )

    supplier_code = generate_next_supplier_code(db)

    from app.services.supplier_mapper import extract_categories
    cats = extract_categories(supplier.principal_business, supplier.material_types)
    supplier_category = ", ".join(cats) if cats else None

    new_supplier = Supplier(
        supplier_code=supplier_code,
        company_name=supplier.company_name or "Unnamed Supplier",
        principal_business=supplier.principal_business,
        gst_number=supplier.gst_number,
        registered_address=supplier.registered_address or "Pending Registration",
        contact_person_name=supplier.contact_person_name or supplier.company_name or "Pending Registration",
        contact_person_email=supplier.contact_person_email,
        whatsapp_number=supplier.whatsapp_number or "0000000000",
        supplier_category=supplier_category,
        material_types=supplier.material_types,
        bank_name=supplier.bank_name or "Pending Registration",
        beneficiary_name=supplier.beneficiary_name or "Pending Registration",
        bank_account_number=supplier.bank_account_number or "Pending Registration",
        bank_ifsc=supplier.bank_ifsc or "Pending Registration",
        branch_name=supplier.branch_name,
        is_msme=supplier.is_msme,
        msme_number=supplier.msme_number,
        msme_certificate_path=supplier.msme_certificate_path,
        gst_certificate_path=supplier.gst_certificate_path,
        references=supplier.references,
        authorized_person_name=supplier.authorized_person_name,
        designation=supplier.designation,
        declaration_accepted=True,  # Verified by PM manually
        registration_status="APPROVED"  # Auto-approved
    )

    db.add(new_supplier)
    db.commit()
    db.refresh(new_supplier)

    return {
        "message": "Supplier Created & Approved Successfully",
        "supplier_id": new_supplier.id,
        "supplier_code": new_supplier.supplier_code
    }


@router.put("/{supplier_id}/update")
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: Session = Depends(get_db)
):
    """Update supplier details manually by PM. Only non-None fields are updated."""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    update_data = payload.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Apply all non-category fields first
    for field, value in update_data.items():
        if field != "supplier_category":          # category is always auto-computed below
            setattr(supplier, field, value)

    # ── Always auto-recalculate supplier_category from the two answer fields ──
    # This mirrors the logic used at registration time (WhatsApp bot & manual creation).
    # One supplier can appear in multiple categories (comma-separated string).
    from app.services.supplier_mapper import extract_categories
    cats = extract_categories(supplier.principal_business, supplier.material_types)
    supplier.supplier_category = ", ".join(cats) if cats else None

    db.commit()
    db.refresh(supplier)

    return {
        "message": "Supplier updated successfully",
        "supplier_id": supplier.id,
        "supplier_category": supplier.supplier_category,
        "updated_fields": list(update_data.keys())
    }


@router.put("/{supplier_id}/approve")
def approve_supplier(
    supplier_id: int,
    approval: SupplierApprovalRequest,
    db: Session = Depends(get_db)
):

    supplier = db.query(
        Supplier
    ).filter(
        Supplier.id == supplier_id
    ).first()

    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found"
        )

    try:
        if not supplier.supplier_code:
            next_val = db.execute(text("SELECT nextval('supplier_code_seq')")).scalar()
            supplier.supplier_code = f"VEND{next_val:06d}"

        supplier.registration_status = "APPROVED"
        supplier.approval_remarks = approval.remarks

        db.commit()
        db.refresh(supplier)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while approving the supplier. Please try again."
        )

    return {
        "message": "Supplier Approved Successfully",
        "supplier_id": supplier.id,
        "status": supplier.registration_status
    }

    


@router.put("/{supplier_id}/reject")
def reject_supplier(
    supplier_id: int,
    rejection: SupplierRejectionRequest,
    db: Session = Depends(get_db)
):

    supplier = db.query(
        Supplier
    ).filter(
        Supplier.id == supplier_id
    ).first()

    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found"
        )

    supplier.registration_status = "REJECTED"
    supplier.approval_remarks = rejection.remarks

    db.commit()
    db.refresh(supplier)

    return {
        "message": "Supplier Rejected Successfully",
        "supplier_id": supplier.id,
        "status": supplier.registration_status
    }


@router.delete("/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db)
):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found"
        )
    try:
        from sqlalchemy import text
        # Delete related child records first to satisfy foreign key constraints
        db.execute(text("DELETE FROM rfq_vendors WHERE vendor_id = :id"), {"id": supplier_id})
        db.execute(text("DELETE FROM whatsapp_inbox_messages WHERE supplier_id = :id"), {"id": supplier_id})
        db.execute(text("DELETE FROM supplier_references WHERE supplier_id = :id"), {"id": supplier_id})
        db.execute(text("DELETE FROM negotiations WHERE vendor_id = :id"), {"id": supplier_id})
        db.execute(text("DELETE FROM reminders_log WHERE vendor_id = :id"), {"id": supplier_id})

        # Delete registration and quotation conversation history so fresh registration starts on next message
        db.execute(text("DELETE FROM supplier_conversations WHERE phone_number = :phone"), {"phone": supplier.whatsapp_number})
        db.execute(text("DELETE FROM supplier_quotation_conversations WHERE phone_number = :phone"), {"phone": supplier.whatsapp_number})

        # Nullify or delete quotations/invoices
        db.execute(text("DELETE FROM quotation_items WHERE quotation_id IN (SELECT id FROM quotations WHERE vendor_id = :id)"), {"id": supplier_id})
        db.execute(text("DELETE FROM quotations WHERE vendor_id = :id"), {"id": supplier_id})

        db.execute(text("DELETE FROM invoice_items WHERE invoice_id IN (SELECT id FROM invoices WHERE vendor_id = :id)"), {"id": supplier_id})
        db.execute(text("DELETE FROM invoices WHERE vendor_id = :id"), {"id": supplier_id})

        # Nullify ingestion logs
        db.execute(text("UPDATE document_ingestion_logs SET supplier_id = NULL WHERE supplier_id = :id"), {"id": supplier_id})

        # Finally delete supplier
        db.delete(supplier)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete supplier due to database constraints: {str(e)}"
        )
    return {
        "message": "Supplier Deleted Successfully",
        "supplier_id": supplier_id
    }


    