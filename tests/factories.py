"""Small builders for database tests. Each commits, so the row is visible to other sessions."""

import itertools

from sqlalchemy.ext.asyncio import AsyncSession

from database import db_tenant
from models import Tenant, User
from schemas.tenant import TenantCreate

_telegram_ids = itertools.count(1_000_000)


async def make_user(db: AsyncSession, first_name: str = "Test") -> User:
    user = User(telegram_id=next(_telegram_ids), first_name=first_name)
    db.add(user)
    await db.commit()
    return user


async def make_tenant(
    db: AsyncSession, slug: str, owner: User | None = None, name: str = "Test store"
) -> Tenant:
    owner = owner or await make_user(db)
    return await db_tenant.create_tenant(db, owner.id, TenantCreate(name=name, slug=slug))