from fastapi import HTTPException, Depends, status, Response, APIRouter, Request
from fastapi.security import OAuth2PasswordRequestForm, OAuth2
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.responses import RedirectResponse, JSONResponse
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import timedelta, datetime
from typing import Optional
from jose import jwt
from jose import JWTError
from config import *
from db.models import User
from db.database import *
from db.schemas import UserSchema, TokenSchema
from typing import Dict
from typing import Optional
from fastapi.openapi.models import OAuthFlows as OAuthFlowsModel
from fastapi.exceptions import HTTPException as StarletteHTTPException

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class OAuth2PasswordBearerWithCookie(OAuth2):
    def __init__(
        self,
        tokenUrl: str,
        scheme_name: Optional[str] = None,
        scopes: Optional[Dict[str, str]] = None,
        auto_error: bool = True,
    ):
        if not scopes:
            scopes = {}
        flows = OAuthFlowsModel(password={"tokenUrl": tokenUrl, "scopes": scopes})
        super().__init__(flows=flows, scheme_name=scheme_name, auto_error=auto_error)

    async def __call__(self, request: Request) -> Optional[str]:
        # 1. Attempt the standard header check first (using the parent OAuth2 logic).
        # This checks for the "Authorization: Bearer <token>" header.
        try:
            return await super().__call__(request)
        except HTTPException:
            # 2. If the standard header check fails, fall back to checking the cookie.
            
            cookie_authorization: str = request.cookies.get("access_token")

            # Check if the cookie exists and contains a value that can be parsed.
            if cookie_authorization:
                scheme, param = get_authorization_scheme_param(cookie_authorization)
                
                # We expect the cookie value to be set as "Bearer <token>"
                if scheme and scheme.lower() == "bearer":
                    # Token found in the cookie, return the raw token string
                    return param
            
            # 3. If neither the header nor the cookie provides a valid token, 
            #    raise the authentication error.
            if self.auto_error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                return None

# OAuth2PasswordBearer for token authentication
oauth2_scheme = OAuth2PasswordBearerWithCookie(tokenUrl="token")

# Function to create access token
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, SECRET_KEY, algorithm=ALGORITHM
    )
    return encoded_jwt

# Function to get a user by username
async def get_user_by_email(email: str, db: Session):
   stmt = select(User).where(User.email == email)
   
   result = await db.execute(stmt)
   
   user = result.scalar_one_or_none()
   
   return user

# Function to verify a user's password
def verify_password(plain_password, hashed_password):
    truncated_password_bytes = plain_password.encode('utf-8')[:72]
    return pwd_context.verify(truncated_password_bytes, hashed_password)

# Function to create a new user
async def create_user(user: UserSchema, db: Session):
    hashed_password = pwd_context.hash(user.password)
    user = User(
        username=user.username,
        email=user.email,
        password=hashed_password,
        phone=user.phone,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# Function to authenticate a user and generate a token
async def authenticate_user(email: str, password: str, db: Session = Depends(get_db)):
    user = await get_user_by_email(email=email, db=db)
    print(user)
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    return user

# Get the current user based on the token
async def get_current_user_from_token(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    
    # 🎯 NEW DEBUG: Log the token string passed to the decoder
    print(f"DEBUG: Attempting to decode token: {token}")

    # 💥 CRITICAL FIX: Ensure the 'Bearer ' prefix is removed if present.
    if token and token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
        print(f"DEBUG: Stripped prefix. New token: {token}")
        
    try:
        payload = jwt.decode(
            token, SECRET_KEY, algorithms=[ALGORITHM]
        )
        email: str = payload.get("sub")
        
        # 1. Check if email (sub) is present in the token payload
        if not email :
            # This is raised if the token payload is corrupt or missing the subject ('sub')
            print("DEBUG: Token payload missing 'sub' (email) field.")
            raise credentials_exception
            
    except JWTError as e:
        # 2. This is the most common failure: token is expired, has the wrong signature, 
        #    or the SECRET_KEY/ALGORITHM is wrong.
        print(f"DEBUG: JWT Error - {e.__class__.__name__}: {e}") # Enhanced print statement
        # Re-raise the exception after logging the specific error
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            # Added a fallback detail just in case the specific error is helpful:
            detail=f"Token Invalid (JWT Error: {e.__class__.__name__})",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # 3. Check if user exists in the database
    user = await get_user_by_email(email=email, db=db)
    if not user:
        # This is raised if the token is valid but points to a deleted user
        print(f"DEBUG: Valid token, but user '{email}' not found in DB.")
        raise credentials_exception
        
    return user

async def unauthorized_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Catches 401 HTTPExceptions raised by the authentication dependency 
    and redirects browser users to the login page.
    """
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        
        # Check if the client expects HTML (i.e., it's a browser request)
        accept_header = request.headers.get("accept", "")
        
        if "text/html" in accept_header:
            print("DEBUG: 401 Unauthorized detected. Redirecting browser client to /login.")
            return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        else:
            # For non-browser clients (API calls), return the standard 401 JSON response
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required. Invalid or missing token."}
            )
    
    # For all other HTTP exceptions (404, 500, etc.), use the default handler
    # Note: request.app.default_exception_handlers is a private API, but reliable for this use case.
    # It must be defined on the app instance, which it will be after the registration below.
    return await request.app.default_exception_handlers[StarletteHTTPException](request, exc)

async def get_authenticated_template_context(
    request: Request,
    current_user: User = Depends(get_current_user_from_token)
) -> dict:
    """
    Authenticates the user and prepares the base context dictionary
    required by the layout.html template.
    """
    # This dependency ensures authentication passes, otherwise it raises 401.
    return {
        "request": request,
        "user": current_user.username,
    }