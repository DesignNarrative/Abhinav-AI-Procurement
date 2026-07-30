from typing import Optional, Dict
from pydantic import BaseModel
from datetime import datetime


# ─────────────────────────────────────────────────────
# Scoring Config Schemas
# ─────────────────────────────────────────────────────

class ScoringWeightsUpdate(BaseModel):
    # criteria_name -> weight percent. Must sum to 100.
    weights: Dict[str, float]


# ─────────────────────────────────────────────────────
# Award Schemas
# ─────────────────────────────────────────────────────

class AwardCreate(BaseModel):
    quotation_id: int
    # Lowest cost, Best value, Fastest delivery, Preferred supplier,
    # Emergency, Director approval, Previous relationship, Single source
    selection_reason: str
    approved_by: str
    remarks: Optional[str] = None


class AwardResponse(BaseModel):
    id: int
    rfq_id: int
    quotation_id: int
    vendor_id: int
    selection_reason: str
    remarks: Optional[str]
    approved_by: str
    awarded_at: datetime

    model_config = {"from_attributes": True}
