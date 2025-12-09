from fastapi import APIRouter
from web.routes import router_main, router_asset, router_strategy, router_auth

router = APIRouter()

router.include_router(router_main.router, prefix="", tags=["asset"])
router.include_router(router_asset.router, prefix="", tags=["asset"])
router.include_router(router_strategy.router, prefix="", tags=["strategy"])
router.include_router(router_auth.router, prefix="", tags=["auth"])
