"""
Pluggable ERP connector layer.

The ERP is not yet decided, so this mirrors the extraction-provider pattern:
an abstract base defines the contract and a `NoOpConnector` is the default
(records a synthetic reference so the queue lifecycle is exercised end-to-end
without any external system). A concrete Tally / REST connector can be added
later and selected via settings without touching the queue or the service.
"""

import abc
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ERPSyncResult:
    """Outcome of a single push attempt to the ERP."""

    def __init__(self, success: bool, reference: str = None, error: str = None):
        self.success = success
        self.reference = reference
        self.error = error


class ERPConnector(abc.ABC):
    """Contract every ERP connector must implement."""

    name = "base"

    @abc.abstractmethod
    def push(self, entity_type: str, entity_id: int, payload: dict) -> ERPSyncResult:
        """Push a single entity to the ERP and return the result."""
        raise NotImplementedError


class NoOpConnector(ERPConnector):
    """
    Default connector used until a real ERP is configured.

    It does not talk to any external system; it simply acknowledges the push
    with a synthetic reference so the sync queue can be driven and tested.
    """

    name = "noop"

    def push(self, entity_type: str, entity_id: int, payload: dict) -> ERPSyncResult:
        ref = f"NOOP-{entity_type.upper()}-{entity_id}-{int(datetime.now().timestamp())}"
        logger.info(
            "NoOpConnector acknowledged %s #%s as %s", entity_type, entity_id, ref
        )
        return ERPSyncResult(success=True, reference=ref)


# Registry of available connectors. Add concrete connectors here when ready.
_CONNECTORS = {
    "noop": NoOpConnector,
}


def get_connector(name: str = None) -> ERPConnector:
    """
    Resolve the active ERP connector.

    Selection order: explicit argument > ERP_CONNECTOR env var > 'noop'.
    Unknown names fall back to the NoOp connector (never raises) so a
    misconfiguration can never break the queue.
    """
    if not name:
        name = os.getenv("ERP_CONNECTOR") or "noop"

    connector_cls = _CONNECTORS.get(str(name).lower(), NoOpConnector)
    return connector_cls()
