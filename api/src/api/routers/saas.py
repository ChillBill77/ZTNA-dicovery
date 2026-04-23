from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session, require_editor
from api.schemas.saas import SaasEntry, SaasIn

router = APIRouter(prefix="/api/saas", tags=["saas"])


@router.get("", response_model=list[SaasEntry])
async def list_saas(session: AsyncSession = Depends(db_session)) -> list[SaasEntry]:
    res = await session.execute(text(
        "SELECT id, name, vendor, fqdn_pattern, category, source, priority "
        "FROM saas_catalog ORDER BY id"
    ))
    return [SaasEntry(**dict(r)) for r in res.mappings().all()]


@router.post("", response_model=SaasEntry, status_code=status.HTTP_201_CREATED)
async def create_saas(
    body: SaasIn,
    _user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> SaasEntry:
    res = await session.execute(text(
        """INSERT INTO saas_catalog (name, vendor, fqdn_pattern, category, source, priority)
           VALUES (:name, :vendor, :fqdn_pattern, :category, 'manual', :priority)
           RETURNING id, name, vendor, fqdn_pattern, category, source, priority"""
    ), body.model_dump())
    await session.commit()
    return SaasEntry(**dict(res.mappings().one()))


@router.put("/{saas_id}", response_model=SaasEntry)
async def update_saas(
    saas_id: int, body: SaasIn,
    _user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> SaasEntry:
    res = await session.execute(text(
        """UPDATE saas_catalog
              SET name=:name, vendor=:vendor, fqdn_pattern=:fqdn_pattern,
                  category=:category, priority=:priority
            WHERE id=:id
            RETURNING id, name, vendor, fqdn_pattern, category, source, priority"""
    ), {**body.model_dump(), "id": saas_id})
    row = res.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="saas entry not found")
    await session.commit()
    return SaasEntry(**dict(row))


@router.delete("/{saas_id}", status_code=204, response_model=None, response_class=Response)
async def delete_saas(
    saas_id: int,
    _user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> None:
    await session.execute(text("DELETE FROM saas_catalog WHERE id=:id"), {"id": saas_id})
    await session.commit()
