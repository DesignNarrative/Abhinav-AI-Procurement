from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Boolean,
    DateTime
)

from sqlalchemy.sql import func

from app.database.database import Base


class ScoringConfig(Base):
    """
    Configurable weights for the quotation comparison scoring engine.
    One row per criteria. Weights are percentages and should sum to 100.

    Default criteria seeded on first use:
        price 40, quality 20, delivery 15,
        payment_terms 10, vendor_rating 10, risk 5
    """
    __tablename__ = "scoring_config"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    criteria_name = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True
    )

    weight = Column(
        Numeric(5, 2),
        nullable=False,
        default=0.0
    )

    is_active = Column(
        Boolean,
        default=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )
