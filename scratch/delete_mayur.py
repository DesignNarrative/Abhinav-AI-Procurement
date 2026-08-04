import sys
sys.path.insert(0, r'c:\Users\Admin\OneDrive\Desktop\Abhinav AI Progurment')

from app.database.database import SessionLocal
# Import all models to populate class registry
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

try:
    supplier = db.query(Supplier).filter(Supplier.company_name == 'Mayur Interiors').first()
    if not supplier:
        print("Mayur Interiors not found in database.")
    else:
        sid = supplier.id
        phone = supplier.whatsapp_number
        print(f"Deleting Mayur Interiors: ID={sid}, Phone={phone}")
        
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
            
        # 5. Delete conversations for Mayur's phone number
        convs_deleted = db.query(SupplierConversation).filter(
            SupplierConversation.phone_number.in_(['8862091694', '918862091694'])
        ).delete(synchronize_session=False)
        print(f"Deleted {convs_deleted} records from SupplierConversation")
        
        # 6. Delete supplier itself
        db.delete(supplier)
        print("Deleted supplier Mayur Interiors.")
        
        db.commit()
        print("Successfully committed deletion of Mayur Interiors.")
except Exception as e:
    db.rollback()
    print(f"Error during deletion: {e}")
finally:
    db.close()
