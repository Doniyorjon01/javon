"""
Staff: invites and members
==========================
The owner (admin panel):
POST   /tenants/{tenant_id}/staff/invites              a one-time link (7 days); shown once
GET    /tenants/{tenant_id}/staff/invites              open invites (no links: only hashes are kept)
DELETE /tenants/{tenant_id}/staff/invites/{invite_id}  revoke
GET    /tenants/{tenant_id}/staff                      who works here, owner first
DELETE /tenants/{tenant_id}/staff/{user_id}            remove a staff member (not the owner)

Staff:
POST   /tenants/{tenant_id}/staff/leave                stop working in this store

The invited person (the frontend page APP_URL/taklif/<token>):
GET    /invites/{token}                                store name, before signing in
POST   /invites/{token}/accept                         signed in: join as staff

How many staff a store may have depends on its plan (utils/plans.py). Invite
routes are rate-limited per IP, so links cannot be guessed by brute force.
"""

from fastapi import APIRouter, Depends, Path, Security, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.oauth2 import CurrentMember, get_current_member, get_current_owner, get_current_user
from database import db_staff
from database.config import get_pg_db
from errors import generate_error
from models.staff import StaffInvite
from models.tenant import MemberRole
from models.user import User
from schemas.base import BIGINT_MAX
from schemas.staff import InviteCreatedOut, InviteOut, InvitePreviewOut, JoinedStoreOut, MemberOut
from translations import Msg
from utils.i18n import Lang, get_lang
from utils.rate_limit import INVITE_LIMIT

router = APIRouter(prefix="/tenants/{tenant_id}/staff", tags=["staff"])
invites_router = APIRouter(prefix="/invites", tags=["staff"], dependencies=[Depends(INVITE_LIMIT)])

InviteToken = Path(min_length=16, max_length=db_staff.MAX_TOKEN_LENGTH, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/invites", response_model=InviteCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InviteCreatedOut:
    return await db_staff.create_invite(db, owner.tenant_id, owner.user.id, lang)


@router.get("/invites", response_model=list[InviteOut])
async def get_invites(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
) -> list[StaffInvite]:
    return await db_staff.get_open_invites(db, owner.tenant_id)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: int = Path(gt=0, le=BIGINT_MAX),
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> None:
    await db_staff.revoke_invite(db, owner.tenant_id, invite_id, lang)


@router.get("", response_model=list[MemberOut])
async def get_members(
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
) -> list[MemberOut]:
    return await db_staff.get_members(db, owner.tenant_id)


@router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_store(
    member: CurrentMember = Security(get_current_member),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> None:
    if member.role == MemberRole.OWNER:
        raise generate_error(Msg.OWNER_CANNOT_LEAVE, lang, status.HTTP_409_CONFLICT)
    await db_staff.remove_member(db, member.tenant_id, member.user.id, lang)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: int = Path(gt=0, le=BIGINT_MAX),
    owner: CurrentMember = Security(get_current_owner),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> None:
    await db_staff.remove_member(db, owner.tenant_id, user_id, lang)


@invites_router.get("/{token}", response_model=InvitePreviewOut)
async def preview_invite(
    token: str = InviteToken,
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> InvitePreviewOut:
    return await db_staff.preview_invite(db, token, lang)


@invites_router.post("/{token}/accept", response_model=JoinedStoreOut)
async def accept_invite(
    token: str = InviteToken,
    user: User = Security(get_current_user),
    db: AsyncSession = Depends(get_pg_db),
    lang: Lang = Depends(get_lang),
) -> JoinedStoreOut:
    return await db_staff.accept_invite(db, token, user.id, lang)
