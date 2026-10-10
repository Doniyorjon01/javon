"""
Storefront API — public, what buyers see
========================================
Everything under /storefront/{slug} is scoped to one store by get_storefront_tenant.
Catalog, search and orders join this router in later steps.
"""

from fastapi import APIRouter, Depends

from auth.tenant import get_storefront_tenant
from models.tenant import Tenant
from schemas.tenant import StorefrontOut

router = APIRouter(prefix="/storefront/{slug}", tags=["storefront"])


@router.get("", response_model=StorefrontOut)
async def get_store(tenant: Tenant = Depends(get_storefront_tenant)) -> Tenant:
    return tenant