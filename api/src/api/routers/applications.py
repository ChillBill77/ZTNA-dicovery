from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import db_session, require_editor
from api.schemas.applications import Application, ApplicationIn, AuditEntry

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.get("", response_model=list[Application])
async def list_apps(
    limit: int = 200,
    offset: int = 0,
    session: AsyncSession = Depends(db_session),
) -> list[Application]:
    res = await session.execute(
        text(
            """SELECT id, name, description, owner, dst_cidr::text AS dst_cidr,
                  dst_port_min, dst_port_max, proto, priority, source,
                  created_at, updated_at, updated_by
           FROM applications ORDER BY priority DESC, id
           LIMIT :limit OFFSET :offset"""
        ),
        {"limit": limit, "offset": offset},
    )
    return [Application(**dict(r)) for r in res.mappings().all()]


@router.post("", response_model=Application, status_code=status.HTTP_201_CREATED)
async def create_app(
    body: ApplicationIn,
    user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> Application:
    res = await session.execute(
        text(
            """INSERT INTO applications (name, description, owner, dst_cidr,
                                     dst_port_min, dst_port_max, proto, priority,
                                     source, updated_by)
           VALUES (:name, :description, :owner, :dst_cidr::cidr,
                   :dst_port_min, :dst_port_max, :proto, :priority,
                   'manual', :updated_by)
           RETURNING id, name, description, owner, dst_cidr::text AS dst_cidr,
                     dst_port_min, dst_port_max, proto, priority, source,
                     created_at, updated_at, updated_by"""
        ),
        {**body.model_dump(), "updated_by": user["upn"]},
    )
    row = res.mappings().one()
    await session.execute(
        text(
            """INSERT INTO application_audit (application_id, changed_by, op, after)
           VALUES (:id, :by, 'create', :after::jsonb)"""
        ),
        {"id": row["id"], "by": user["upn"], "after": Application(**dict(row)).model_dump_json()},
    )
    await session.commit()
    return Application(**dict(row))


@router.put("/{app_id}", response_model=Application)
async def update_app(
    app_id: int,
    body: ApplicationIn,
    user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> Application:
    before_res = await session.execute(
        text(
            """SELECT id, name, description, owner, dst_cidr::text AS dst_cidr,
                  dst_port_min, dst_port_max, proto, priority, source,
                  created_at, updated_at, updated_by
           FROM applications WHERE id = :id"""
        ),
        {"id": app_id},
    )
    before = before_res.mappings().first()
    if before is None:
        raise HTTPException(status_code=404, detail="application not found")

    res = await session.execute(
        text(
            """UPDATE applications
              SET name=:name, description=:description, owner=:owner,
                  dst_cidr=:dst_cidr::cidr, dst_port_min=:dst_port_min,
                  dst_port_max=:dst_port_max, proto=:proto, priority=:priority,
                  updated_at=now(), updated_by=:updated_by
            WHERE id=:id
            RETURNING id, name, description, owner, dst_cidr::text AS dst_cidr,
                      dst_port_min, dst_port_max, proto, priority, source,
                      created_at, updated_at, updated_by"""
        ),
        {**body.model_dump(), "id": app_id, "updated_by": user["upn"]},
    )
    after = res.mappings().one()
    await session.execute(
        text(
            """INSERT INTO application_audit (application_id, changed_by, op, before, after)
           VALUES (:id, :by, 'update', :before::jsonb, :after::jsonb)"""
        ),
        {
            "id": app_id,
            "by": user["upn"],
            "before": Application(**dict(before)).model_dump_json(),
            "after": Application(**dict(after)).model_dump_json(),
        },
    )
    await session.commit()
    return Application(**dict(after))


@router.delete("/{app_id}", status_code=204, response_model=None, response_class=Response)
async def delete_app(
    app_id: int,
    user: dict = Depends(require_editor),  # TODO(P4): require role=editor
    session: AsyncSession = Depends(db_session),
) -> None:
    # Write audit BEFORE delete because of ON DELETE CASCADE on application_audit.
    before_res = await session.execute(
        text(
            """SELECT id, name, description, owner, dst_cidr::text AS dst_cidr,
                  dst_port_min, dst_port_max, proto, priority, source,
                  created_at, updated_at, updated_by
           FROM applications WHERE id=:id"""
        ),
        {"id": app_id},
    )
    before = before_res.mappings().first()
    if before is None:
        raise HTTPException(status_code=404, detail="application not found")
    # TODO(P4): move audit table off CASCADE semantics so the delete-op row
    # survives the application row it references. For P2 the audit trail is
    # lost on hard delete; operators should prefer update over delete.
    await session.execute(text("DELETE FROM applications WHERE id = :id"), {"id": app_id})
    await session.commit()


@router.get("/{app_id}/audit", response_model=list[AuditEntry])
async def get_audit(
    app_id: int,
    session: AsyncSession = Depends(db_session),
) -> list[AuditEntry]:
    res = await session.execute(
        text(
            """SELECT id, application_id, changed_at, changed_by, op, before, after
           FROM application_audit WHERE application_id = :id
           ORDER BY changed_at DESC"""
        ),
        {"id": app_id},
    )
    return [AuditEntry(**dict(r)) for r in res.mappings().all()]
