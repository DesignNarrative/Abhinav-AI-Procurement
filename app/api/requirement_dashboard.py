from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db

from app.services.requirement_service import RequirementService

router = APIRouter(
    prefix="/dashboard/requirements",
    tags=["Requirement Dashboard"]
)

templates = Jinja2Templates(
    directory="app/templates"
)


# =====================================================
# Requirement List
# =====================================================

@router.get(
    "/",
    response_class=HTMLResponse
)
def requirement_management(
    request: Request,
    db: Session = Depends(get_db),
    search: str = "",
    status: str = ""
):

    requirements = RequirementService.get_all_requirements(
        db=db,
        search=search,
        status=status
    )

    return templates.TemplateResponse(
        request=request,
        name="requirement_management.html",
        context={
            "request": request,
            "requirements": requirements,
            "search": search,
            "status": status
        }
    )


# =====================================================
# Create Requirement Page (merged into unified RFQ page)
# =====================================================

@router.get(
    "/create"
)
def create_requirement_page():
    """Requirements creation is merged into the unified RFQ page.

    Kept as a permanent redirect so old links/bookmarks keep working.
    """
    return RedirectResponse(
        url="/dashboard/rfq/create",
        status_code=307
    )


# =====================================================
# Requirement Details
# =====================================================

@router.get(
    "/{requirement_id}",
    response_class=HTMLResponse
)
def requirement_details(
    requirement_id: int,
    request: Request,
    db: Session = Depends(get_db)
):

    requirement = RequirementService.get_requirement_by_id(
        db=db,
        requirement_id=requirement_id
    )

    if not requirement:
        raise HTTPException(
            status_code=404,
            detail="Requirement not found"
        )

    materials = requirement.materials or []

    return templates.TemplateResponse(
        request=request,
        name="requirement_details.html",
        context={
            "request": request,
            "requirement": requirement,
            "materials": materials,
            "material_count": len(materials),
            "can_generate_rfq": len(materials) > 0
        }
    )