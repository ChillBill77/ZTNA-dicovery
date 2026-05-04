from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class GroupsService:
    """Paginated read access to ``user_groups``.

    Pagination uses an opaque ``cursor`` that encodes the last ``user_upn``
    returned on the prior page. Lexicographic ordering over ``user_upn`` keeps
    the cursor stable across writes (new members appended alphabetically only
    affect pages after the insertion point).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def _encode_cursor(last_upn: str) -> str:
        return urlsafe_b64encode(last_upn.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decode_cursor(cursor: str) -> str:
        try:
            return urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise ValueError(f"invalid cursor: {exc}") from exc

    async def get_members(
        self,
        group_id: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, Any] | None:
        after = self._decode_cursor(cursor) if cursor else ""

        # Total size check; returns 0 when the group has no members or does not exist.
        size_row = (
            (
                await self._db.execute(
                    text(
                        "SELECT COUNT(*) AS n, MAX(group_name) AS group_name "
                        "FROM user_groups WHERE group_id = :id"
                    ),
                    {"id": group_id},
                )
            )
            .mappings()
            .first()
        )
        size = int(size_row["n"]) if size_row else 0
        if size == 0:
            return None
        group_name = size_row["group_name"] or group_id

        rows = (
            (
                await self._db.execute(
                    text(
                        "SELECT user_upn FROM user_groups "
                        "WHERE group_id = :id AND user_upn > :after "
                        "ORDER BY user_upn "
                        "LIMIT :limit"
                    ),
                    {"id": group_id, "after": after, "limit": page_size},
                )
            )
            .scalars()
            .all()
        )
        members = [str(r) for r in rows]
        next_cursor = self._encode_cursor(members[-1]) if len(members) == page_size else None
        return {
            "group_id": group_id,
            "group_name": group_name,
            "size": size,
            "members": members,
            "next_cursor": next_cursor,
        }
