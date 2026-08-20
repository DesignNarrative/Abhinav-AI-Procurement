from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey
)
from sqlalchemy.sql import func
from app.database.database import Base


class WhatsAppInboxMessage(Base):
    __tablename__ = "whatsapp_inbox_messages"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # Which supplier this message belongs to (nullable for unregistered suppliers during onboarding)
    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # The raw phone number (normalized to digits only, e.g. 918862091694)
    supplier_phone = Column(
        String(20),
        nullable=False
    )

    # The message text content
    message_text = Column(
        Text,
        nullable=False
    )

    # "inbound"  = supplier sent to PM
    # "outbound" = PM sent to supplier
    direction = Column(
        String(10),
        nullable=False,
        default="inbound"
    )

    # Has the PM read this message? (only relevant for inbound)
    is_read = Column(
        Boolean,
        default=False,
        nullable=False
    )

    # Rich features
    media_type = Column(
        String(10),
        default="text",
        nullable=False
    )  # "text", "image", "video", "document"

    media_path = Column(
        String(255),
        nullable=True
    )

    is_deleted_for_me = Column(
        Boolean,
        default=False,
        nullable=False
    )

    is_deleted_for_everyone = Column(
        Boolean,
        default=False,
        nullable=False
    )

    is_edited = Column(
        Boolean,
        default=False,
        nullable=False
    )

    whatsapp_message_id = Column(
        String(100),
        nullable=True
    )

    delivery_status = Column(
        String(50),
        nullable=True,
        default="sent"
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
