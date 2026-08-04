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
    SupplierRejectionRequest
)

router = APIRouter(
    prefix="/suppliers",
    tags=["Suppliers"]
)


@router.get("/")
def get_suppliers(db: Session = Depends(get_db)):
    return db.query(Supplier).all()


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

    