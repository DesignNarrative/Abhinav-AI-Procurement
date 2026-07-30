from pydantic import BaseModel
from typing import Optional, Dict, Any


# =====================================================
# Enqueue an entity for ERP sync
# =====================================================

class ERPEnqueue(BaseModel):
    entity_type: str
    entity_id: int
    payload: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None
