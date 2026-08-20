# Import ALL models here so SQLAlchemy mapper resolves all relationships at startup
# This prevents "failed to locate a name" errors when querying any model

from app.models.supplier import Supplier
from app.models.supplier_conversation import SupplierConversation
from app.models.supplier_quotation_conversation import SupplierQuotationConversation
from app.models.supplier_reference import SupplierReference

from app.models.requirement import Requirement
from app.models.requirement_material import RequirementMaterial

from app.models.rfq import RFQ
from app.models.rfq_item import RFQItem
from app.models.rfq_vendor import RFQVendor
from app.models.rfq_award import RFQAward

from app.models.quotation import Quotation
from app.models.quotation_item import QuotationItem
from app.models.scoring_config import ScoringConfig
from app.models.negotiation import Negotiation

from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem

from app.models.delivery import Delivery
from app.models.delivery_item import DeliveryItem

from app.models.invoice import Invoice
from app.models.invoice_item import InvoiceItem

from app.models.payment import Payment

from app.models.document_ingestion_log import DocumentIngestionLog
from app.models.erp_sync_queue import ERPSyncQueue
from app.models.reminder_log import ReminderLog

from app.models.whatsapp_inbox_message import WhatsAppInboxMessage
from app.models.user import User
