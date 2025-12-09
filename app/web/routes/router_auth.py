from fastapi import APIRouter, Request, Depends, status
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from web.auth.forms import *
from web.auth.auth import *
from db.schemas import UserSchema
from db.models import *
from db.database import *

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
            response = RedirectResponse(url="/assets", status_code=status.HTTP_302_FOUND)
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
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return {"access_token": access_token, "token_type": "bearer"}

# Protected route that requires authentication
@router.get("/protected")
async def protected_route(current_user: User = Depends(get_current_user_from_token)):
    return {"message": "You have access to this protected route."}