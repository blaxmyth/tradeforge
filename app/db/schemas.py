from pydantic import BaseModel, ConfigDict

class AssetSchema(BaseModel):
    id: int
    symbol: str
    name: str
    asset_class: str
    is_sp500: bool

    model_config = ConfigDict(from_attributes=True)

class UserSchema(BaseModel):
    username: str
    email: str
    password: str
    phone: str

class TokenSchema(BaseModel):
    access_token: str
    token_type: str