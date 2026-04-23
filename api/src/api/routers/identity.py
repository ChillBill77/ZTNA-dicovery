from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session
from api.schemas.identity import IdentityResolution
from api.services.identity_service import IdentityService

router = APIRouter(prefix="/api/identity", tags=["identity"])


def _identity_service(
    session: AsyncSession = Depends(db_session),
) -> IdentityService:
    return IdentityService(session)


@router.get("/resolve", response_model=IdentityResolution)
async def resolve(
    src_ip: str = Query(..., examples=["10.0.12.34"]),
    at: datetime = Query(...),
    svc: IdentityService = Depends(_identity_service),
) -> IdentityResolution:
    hit = await svc.resolve(src_ip, at)
    if hit is None:
        return IdentityResolution(user_upn=None)
    return IdentityResolution(**hit)
