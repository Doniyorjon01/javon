"""Small builders for database tests. Each commits, so the row is visible to other sessions."""

import itertools

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from database import db_tenant
from models import MemberRole, Membership, Tenant, User
from schemas.tenant import TenantCreate

_telegram_ids = itertools.count(1_000_000)


async def make_user(db: AsyncSession, first_name: str = "Test", *, is_platform_admin: bool = False) -> User:
    user = User(telegram_id=next(_telegram_ids), first_name=first_name, is_platform_admin=is_platform_admin)
    db.add(user)
    await db.commit()
    return user


async def make_tenant(
    db: AsyncSession, slug: str, owner: User | None = None, name: str = "Test store"
) -> Tenant:
    owner = owner or await make_user(db)
    return await db_tenant.create_tenant(db, owner.id, TenantCreate(name=name, slug=slug))


async def add_member(db: AsyncSession, tenant: Tenant, user: User, role: MemberRole) -> Membership:
    membership = Membership(user_id=user.id, tenant_id=tenant.id, role=role)
    db.add(membership)
    await db.commit()
    return membership


async def sign_in(client: AsyncClient, user: User) -> None:
    """Sign the client in as `user` through the dev-login route; the cookie stays on the client."""
    resp = await client.post(
        "/auth/dev-login", json={"telegram_id": user.telegram_id, "first_name": user.first_name}
    )
    assert resp.status_code == 200, resp.text
