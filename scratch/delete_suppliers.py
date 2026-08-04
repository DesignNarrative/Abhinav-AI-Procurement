import sys
sys.path.insert(0, r'c:\Users\Admin\OneDrive\Desktop\Abhinav AI Progurment')

from app.database.database import SessionLocal
from app.models.supplier import Supplier
from app.models.supplier_conversation import SupplierConversation
from app.models.supplier_reference import SupplierReference
from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.whatsapp_inbox_message import WhatsAppInboxMessage
from app.models.requirement import Requirement
from app.models.requirement_material import RequirementMaterial

db = SessionLocal()

target_ids = [10, 11]  # Arjun Enterprises (10), Vidhi designs (11)
target_phones = ['9139548675', '919139548675', '8329728303', '918329728303']

try:
    for sid in target_ids:
        supplier = db.query(Supplier).filter(Supplier.id == sid).first()
        if not supplier:
            print(f"Supplier ID {sid} not found in database.")
            continue
            
        print(f"Deleting Supplier: ID={sid}, Name={supplier.company_name}, Phone={supplier.whatsapp_number}")
        
        # 1. Delete inbox messages
        inbox_deleted = db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.supplier_id == sid).delete()
        print(f"Deleted {inbox_deleted} records from WhatsAppInboxMessage")
        
        # 2. Delete RFQ vendor associations
        rfq_vendor_deleted = db.query(RFQVendor).filter(RFQVendor.vendor_id == sid).delete()
        print(f"Deleted {rfq_vendor_deleted} records from RFQVendor")
        
        # 3. Delete supplier references
        refs_deleted = db.query(SupplierReference).filter(SupplierReference.supplier_id == sid).delete()
        print(f"Deleted {refs_deleted} records from SupplierReference")
        
        # 4. Delete quotations
        quotations = db.query(Quotation).filter(Quotation.vendor_id == sid).all()
        q_ids = [q.id for q in quotations]
        if q_ids:
            q_items_deleted = db.query(QuotationItem).filter(QuotationItem.quotation_id.in_(q_ids)).delete(synchronize_session=False)
            print(f"Deleted {q_items_deleted} records from QuotationItem")
            q_deleted = db.query(Quotation).filter(Quotation.vendor_id == sid).delete(synchronize_session=False)
            print(f"Deleted {q_deleted} records from Quotation")
            
        # 5. Delete supplier itself
        db.delete(supplier)
        print(f"Deleted supplier {supplier.company_name} record.")
        
    # 6. Delete conversations for these phone numbers
    convs_deleted = db.query(SupplierConversation).filter(
        SupplierConversation.phone_number.in_(target_phones)
    ).delete(synchronize_session=False)
    print(f"Deleted {convs_deleted} records from SupplierConversation")
    
    # 7. Also delete any orphaned inbox messages that don't have supplier_id but match these phone numbers
    inbox_orphaned = db.query(WhatsAppInboxMessage).filter(
        WhatsAppInboxMessage.supplier_phone.in_(target_phones)
    ).delete(synchronize_session=False)
    print(f"Deleted {inbox_orphaned} orphaned records from WhatsAppInboxMessage")
    
    db.commit()
    print("Successfully committed deletions.")
except Exception as e:
    db.rollback()
    print(f"Error during deletion: {e}")
finally:
    db.close()
