"""Small builders for database tests. Each commits, so the row is visible to other sessions."""

import itertools

from httpx import AsyncClient
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import db_catalog, db_tenant
from database.config import SessionLocal, bind_tenant
from models import Book, BookStatus, InventoryItem, MemberRole, Membership, Tenant, User
from schemas.catalog import BookCreate
from schemas.tenant import TenantCreate

_telegram_ids = itertools.count(1_000_000)


async def make_user(
    db: AsyncSession, first_name: str = "Test", *, is_platform_admin: bool = False, max_stores: int = 1
) -> User:
    user = User(
        telegram_id=next(_telegram_ids),
        first_name=first_name,
        is_platform_admin=is_platform_admin,
        max_stores=max_stores,
    )
    db.add(user)
    await db.commit()
    return user


async def make_tenant(
    db: AsyncSession,
    slug: str,
    owner: User | None = None,
    name: str = "Test store",
    *,
    launched: bool = True,
) -> Tenant:
    """A store through the real create path. Launched by default, so its storefront is
    public (set directly: the real launch also wants a book on the shelf)."""
    owner = owner or await make_user(db)
    tenant = await db_tenant.create_tenant(db, owner.id, TenantCreate(name=name, slug=slug))
    if launched:
        await db.execute(update(Tenant).where(Tenant.id == tenant.id).values(launched_at=func.now()))
        await db.commit()
        await db.refresh(tenant)
    return tenant


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


async def make_book(
    db: AsyncSession, title: str = "Kitob", authors: list[str] | None = None, **fields: object
) -> Book:
    """An approved catalog book, as if loaded by the platform."""
    data = BookCreate(title=title, authors=authors or ["Muallif Bir"], **fields)
    return await db_catalog.create_book(db, data, tenant_id=None, book_status=BookStatus.APPROVED)


async def make_item(
    tenant: Tenant, book: Book, *, price: int = 4_500_000, quantity: int = 5, is_visible: bool = True
) -> InventoryItem:
    """Put a book on a store's shelf (own session bound to the store: RLS)."""
    async with SessionLocal() as session:
        await bind_tenant(session, tenant.id)
        item = InventoryItem(
            tenant_id=tenant.id, book_id=book.id, price=price, quantity=quantity, is_visible=is_visible
        )
        session.add(item)
        await session.commit()
        return item
