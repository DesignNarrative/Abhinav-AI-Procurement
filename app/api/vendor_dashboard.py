from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(
    prefix="/dashboard/vendor-master",
    tags=["Vendor Master Dashboard"]
)

@router.get(
    "/",
    response_class=RedirectResponse
)
def vendor_master():
    """Redirect old Vendor Master route to the unified Supplier Management page pre-filtered for Approved status."""
    return RedirectResponse(url="/dashboard/suppliers?status=APPROVED")
