from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import db_tenant
from models import MemberRole, Membership, Plan, TenantStatus
from schemas.tenant import TenantCreate, TenantUpdate
from tests.factories import make_tenant, make_user

pytestmark = pytest.mark.db


async def test_create_tenant_starts_trial_with_owner(db: AsyncSession) -> None:
    owner = await make_user(db)
    tenant = await db_tenant.create_tenant(db, owner.id, TenantCreate(name="Varaq", slug="varaq"))

    assert tenant.status == TenantStatus.TRIAL
    assert tenant.plan == Plan.STANDARD
    expected_end = datetime.now(UTC) + timedelta(days=settings.TRIAL_DAYS)
    assert abs(tenant.trial_ends_at - expected_end) < timedelta(minutes=1)
    # Server defaults came back from the database.
    assert tenant.theme == "classic"
    assert tenant.languages == ["uz"]

    memberships = list(await db.scalars(select(Membership).where(Membership.tenant_id == tenant.id)))
    assert [(m.user_id, m.role) for m in memberships] == [(owner.id, MemberRole.OWNER)]


async def test_duplicate_slug_is_a_409_not_a_500(db: AsyncSession) -> None:
    await make_tenant(db, "varaq")
    other = await make_user(db)
    with pytest.raises(HTTPException) as exc_info:
        await db_tenant.create_tenant(db, other.id, TenantCreate(name="Boshqa", slug="varaq"))
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "slug_taken"
    # The session is usable after the failed insert.
    assert await db_tenant.get_taken_slugs(db, ["varaq"]) == {"varaq"}


async def test_reserved_slug_is_refused(db: AsyncSession) -> None:
    owner = await make_user(db)
    with pytest.raises(HTTPException) as exc_info:
        await db_tenant.create_tenant(db, owner.id, TenantCreate(name="Admin", slug="admin"))
    assert exc_info.value.detail["code"] == "slug_reserved"


async def test_one_person_can_own_several_stores_when_allowed(db: AsyncSession) -> None:
    owner = await make_user(db, max_stores=2)
    await make_tenant(db, "varaq", owner)
    await make_tenant(db, "varaq-chilonzor", owner)
    count = len(list(await db.scalars(select(Membership).where(Membership.user_id == owner.id))))
    assert count == 2


async def test_a_store_cannot_have_two_owners(db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    intruder = await make_user(db)
    db.add(Membership(user_id=intruder.id, tenant_id=tenant.id, role=MemberRole.OWNER))
    with pytest.raises(IntegrityError, match="uq_memberships_one_owner"):
        await db.commit()
    await db.rollback()


async def test_deleted_store_keeps_its_slug(db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq")
    tenant.is_active = False
    await db.commit()

    result = await db_tenant.check_slug(db, "varaq")
    assert result.available is False
    assert result.reason == "taken"


async def test_check_slug_offers_free_alternatives(db: AsyncSession) -> None:
    await make_tenant(db, "varaq")
    await make_tenant(db, "varaq-kitob")

    result = await db_tenant.check_slug(db, "varaq")
    assert result.available is False
    assert result.suggestions == ["varaq-books", "varaq-uz", "varaq-2"]


async def test_check_slug_cleans_invalid_input(db: AsyncSession) -> None:
    result = await db_tenant.check_slug(db, "varaq!!")
    assert result.reason == "invalid"
    assert result.suggestions[0] == "varaq"


async def test_update_tenant_changes_only_sent_fields(db: AsyncSession) -> None:
    tenant = await make_tenant(db, "varaq", name="Varaq")
    updated = await db_tenant.update_tenant(
        db,
        tenant.id,
        TenantUpdate(
            accent_color="#1F4D3F",
            phone="+998 90 123 45 67",
            latitude=41.311,
            longitude=69.279,
            working_hours={"mon": {"open": "09:00", "close": "20:00"}, "sun": None},
            languages=["uz", "ru"],
        ),
    )
    assert updated.name == "Varaq"  # untouched
    assert updated.accent_color == "#1F4D3F"
    assert updated.phone == "+998901234567"
    assert updated.working_hours == {"mon": {"open": "09:00:00", "close": "20:00:00"}, "sun": None}
    assert updated.languages == ["uz", "ru"]
    assert updated.updated_at > updated.created_at

    cleared = await db_tenant.update_tenant(
        db, tenant.id, TenantUpdate(phone="", latitude=None, longitude=None)
    )
    assert cleared.phone is None
    assert cleared.latitude is None
    assert cleared.accent_color == "#1F4D3F"


async def test_update_missing_tenant_is_404(db: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await db_tenant.update_tenant(db, 999_999, TenantUpdate(name="Yangi nom"))
    assert exc_info.value.status_code == 404
