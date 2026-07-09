import random
from fastapi import APIRouter, Request, Depends, status
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from web.auth.forms import *
from web.auth.auth import *
from db.schemas import UserSchema
from db.models import *
from db.database import *
from config import redis_client, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_PHONE

templates = Jinja2Templates(directory="/app/web/templates")
router = APIRouter(include_in_schema=False)

@router.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")
    return response

@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = LoginForm(request)
    await form.load_data()
    if await form.is_valid():
        try:
            form.__dict__.update(msg="Login Successful :)")
            response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
            await login_for_access_token(response=response, form_data=form, db=db)
            return response
        except HTTPException:
            form.__dict__.update(msg="")
            form.__dict__.get("errors").append("Incorrect Email or Password")
            return templates.TemplateResponse("login.html", form.__dict__)
    return templates.TemplateResponse("login.html", form.__dict__)

@router.get("/register", response_class=HTMLResponse)
async def register(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@router.post("/register")
async def register(request : Request, db: Session = Depends(get_db)):
    form = UserCreateForm(request)
    await form.load_data()
    if await form.is_valid():
        existing_user = await get_user_by_email(email=form.email, db=db)
        if existing_user:
            form.__dict__.get("errors").append("This email is already in use")
            return templates.TemplateResponse("register.html", form.__dict__)
        
        truncated_password = form.password.encode('utf-8')[:72].decode('utf-8')

        user = UserSchema(
            username=form.username, 
            email=form.email, 
            password=truncated_password, # Use the truncated password
            phone=form.phone
        )
        try:
            user = await create_user(user=user, db=db)
            return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
        except IntegrityError:
            form.__dict__.get("errors").append("Duplicate username or email")
            return templates.TemplateResponse("register.html", form.__dict__)
    return templates.TemplateResponse("register.html", form.__dict__)

# Authentication route to generate a token
@router.post("/token")
async def login_for_access_token(
    response: Response, 
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    ):
    user = await authenticate_user(form_data.email, form_data.password, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True,
                        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/api/refresh")
async def refresh_token(response: Response, current_user: User = Depends(get_current_user_from_token)):
    """Slide the session window — called by the client every 20 minutes."""
    token = create_access_token(data={"sub": current_user.email})
    response.set_cookie(key="access_token", value=f"Bearer {token}", httponly=True,
                        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return {"ok": True}

# Protected route that requires authentication
@router.get("/protected")
async def protected_route(current_user: User = Depends(get_current_user_from_token)):
    return {"message": "You have access to this protected route."}


# ── SMS one-time code login ────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    return ''.join(c for c in raw if c.isdigit())

def _e164(digits: str) -> str:
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    return f"+{digits}"

async def _send_otp(phone_digits: str) -> None:
    otp = str(random.randint(100000, 999999))
    await redis_client.set(f"sms_otp:{phone_digits}", otp, ex=600)
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_PHONE:
        from twilio.rest import Client
        Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
            body=f"Your TradeForge code: {otp}",
            from_=TWILIO_FROM_PHONE,
            to=_e164(phone_digits),
        )
    else:
        print(f"[SMS OTP] {phone_digits}: {otp}")


@router.get("/login-sms", response_class=HTMLResponse)
async def login_sms_get(request: Request):
    return templates.TemplateResponse("login_sms.html", {"request": request, "errors": []})


@router.post("/login-sms", response_class=HTMLResponse)
async def login_sms_post(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    phone = _normalize_phone(form.get("phone", ""))

    if len(phone) < 10:
        return templates.TemplateResponse("login_sms.html", {
            "request": request, "errors": ["Please enter a valid phone number."]
        })

    cooldown_key = f"sms_otp_cooldown:{phone}"
    if await redis_client.get(cooldown_key):
        return templates.TemplateResponse("login_sms.html", {
            "request": request,
            "errors": ["Please wait 60 seconds before requesting another code."],
        })

    row = (await db.execute(
        text("SELECT id FROM \"user\" WHERE regexp_replace(phone, '[^0-9]', '', 'g') = :p"),
        {"p": phone},
    )).fetchone()

    if not row:
        return templates.TemplateResponse("login_sms.html", {
            "request": request, "errors": ["No account found with that phone number."]
        })

    await redis_client.set(cooldown_key, "1", ex=60)
    await _send_otp(phone)
    return RedirectResponse(url=f"/login-sms/verify?phone={phone}", status_code=303)


@router.get("/login-sms/verify", response_class=HTMLResponse)
async def login_sms_verify_get(request: Request):
    phone = request.query_params.get("phone", "")
    return templates.TemplateResponse("login_sms_verify.html", {
        "request": request, "phone": phone, "errors": []
    })


@router.post("/login-sms/verify", response_class=HTMLResponse)
async def login_sms_verify_post(request: Request, db: AsyncSession = Depends(get_db)):
    form   = await request.form()
    phone  = _normalize_phone(form.get("phone", ""))
    code   = (form.get("code") or "").strip()

    stored = await redis_client.get(f"sms_otp:{phone}")
    if not stored or stored != code:
        return templates.TemplateResponse("login_sms_verify.html", {
            "request": request, "phone": phone,
            "errors": ["Invalid or expired code. Please try again."],
        })

    await redis_client.delete(f"sms_otp:{phone}")

    row = (await db.execute(
        text("SELECT email FROM \"user\" WHERE regexp_replace(phone, '[^0-9]', '', 'g') = :p"),
        {"p": phone},
    )).fetchone()

    if not row:
        return RedirectResponse(url="/login-sms", status_code=303)

    token = create_access_token(data={"sub": row.email})
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=f"Bearer {token}", httponly=True,
                        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return response