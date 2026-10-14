"""
Internal routes (for Caddy, never public)
=========================================
GET /internal/tls-ask?domain=varaq.javon.uz

Caddy issues HTTPS certificates for store subdomains on demand, at the first
visit, and asks this route first: 200 = this is one of our stores, go ahead;
404 = refuse (otherwise anyone could point random names at the server and make
it request certificates until Let's Encrypt rate-limits us).

Only <slug>.BASE_DOMAIN with an existing store (any status: a certificate for a
store that is closed today is harmless and saves a delay when it reopens).
The Caddyfile answers 404 for /internal/* from the internet; Caddy reaches this
route over the Docker network.
"""

import re

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.config import get_pg_db
from models.tenant import Tenant

router = APIRouter(prefix="/internal", include_in_schema=False)

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@router.get("/tls-ask")
async def tls_ask(
    domain: str = Query(max_length=253),
    db: AsyncSession = Depends(get_pg_db),
) -> Response:
    suffix = "." + settings.BASE_DOMAIN.lower()
    host = domain.strip().lower().rstrip(".")
    label = host.removesuffix(suffix)
    if not host.endswith(suffix) or not _LABEL.match(label):
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    found = await db.scalar(select(Tenant.id).where(Tenant.slug == label, Tenant.is_active.is_(True)))
    return Response(status_code=status.HTTP_200_OK if found else status.HTTP_404_NOT_FOUND)
