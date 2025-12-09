from typing import List
from typing import Optional
from fastapi import Request
import re

validate_phone_number_pattern = "^\\+?\\d{1,4}?[-.\\s]?\\(?\\d{1,3}?\\)?[-.\\s]?\\d{1,4}[-.\\s]?\\d{1,4}[-.\\s]?\\d{1,9}$"
password_pattern = "^(?=.*?[A-Z])(?=.*?[a-z])(?=.*?[0-9])(?=.*?[#?!@$%^&*-]).{8,}$"
email_validate_pattern = r"^\S+@\S+\.\S+$"

class UserCreateForm:
    def __init__(self, request: Request):
        self.request: Request = request
        self.errors: List = []
        self.username: Optional[str] = None
        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self.confirmPassword: Optional[str] = None
        self.phone: Optional[str] = None

    async def load_data(self):
        form = await self.request.form()
        self.username = form.get("username")
        self.email = form.get("email")
        self.password = form.get("password")
        self.confirmPassword =form.get("confirmPassword")
        self.phone = form.get("phonenumber")
    
    async def is_valid(self):

        if not self.username:
            self.errors.append("Username is required")
        if not self.email or not re.match(email_validate_pattern, self.email):
            self.errors.append("A valid email is required")
        if not self.password or not len(self.password) >=8:
            self.errors.append("Password must be greater than 8")
        elif not self.password == self.confirmPassword:
            self.errors.append("Password is not equal")
        elif not re.match(password_pattern, self.password):
            self.errors.append("Password must include at leat one uppercase letter, lowercase letter, digit, special character.")
        if not re.match(validate_phone_number_pattern, self.phone):
            self.errors.append("A valid phone number is required.")
        if not self.errors:
            return True
        return False
        
class LoginForm:
    def __init__(self, request: Request):
        self.request: Request = request
        self.errors: List = []
        self.email: Optional[str] = None
        self.password: Optional[str] = None

    async def load_data(self):
        form = await self.request.form()
        self.email = form.get(
            "email"
        )  
        self.password = form.get("password")

    async def is_valid(self):
        if not self.email or not re.match(email_validate_pattern, self.email):
            self.errors.append("A valid email is required")
        if not self.password or not len(self.password) >= 8 or not re.match(password_pattern, self.password):
            self.errors.append("A valid password is required")
        if not self.errors:
            return True
        return False
