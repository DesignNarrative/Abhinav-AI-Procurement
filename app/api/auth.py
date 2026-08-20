"""
Authentication API routes.
Login via form POST → sets JWT in HTTP-only cookie.
Protected routes check cookie.
"""

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.services.auth_service import authenticate_user, create_access_token, decode_token

router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="app/templates")

COOKIE_NAME = "procurement_token"


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # If already logged in, redirect to dashboard
    token = request.cookies.get(COOKIE_NAME)
    if token and decode_token(token):
        return RedirectResponse(url="/dashboard/", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "error": None}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"request": request, "error": "Invalid username or password."}
        )

    token = create_access_token(data={
        "sub": user.username,
        "role": user.role,
        "full_name": user.full_name or user.username
    })

    response = RedirectResponse(url="/dashboard/", status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=60 * 60 * 8,  # 8 hours
        samesite="lax",
        secure=False  # Set to True when using HTTPS in production
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# ─── Dependency for protected routes ──────────────────────────────────────────

def get_current_user(request: Request):
    """
    Dependency to protect dashboard routes.
    Returns decoded token payload or redirects to login.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return payload


def require_login(request: Request):
    """
    Middleware-style dependency that redirects to /auth/login if not logged in.
    Use as a route dependency: Depends(require_login)
    """
    from fastapi.responses import RedirectResponse
    token = request.cookies.get(COOKIE_NAME)
    if not token or not decode_token(token):
        # Return redirect response by raising HTTPException with redirect
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(
            status_code=307,
            headers={"Location": "/auth/login"}
        )
    return decode_token(token)
