from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.roles import require_role
from api.dependencies import db_session
from api.schemas.groups import GroupMembers
from api.services.groups_service import GroupsService

router = APIRouter(
    prefix="/api/groups",
    tags=["groups"],
    dependencies=[require_role("viewer")],
)


def _groups_service(
    session: AsyncSession = Depends(db_session),
) -> GroupsService:
    return GroupsService(session)


@router.get("/{group_id}", response_model=GroupMembers)
async def get_group(
    group_id: str,
    page_size: int = Query(100, ge=1, le=200),
    cursor: str | None = None,
    svc: GroupsService = Depends(_groups_service),
) -> GroupMembers:
    try:
        result = await svc.get_members(
            group_id, cursor=cursor, page_size=page_size
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="group not found")
    return GroupMembers(**result)
