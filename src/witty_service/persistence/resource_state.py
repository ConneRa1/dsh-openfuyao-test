"""资源表的通用持久化操作：更新哨兵、条件占位、中断恢复。

三个 openFuyao 资源表（Environment / Cluster / App）与渠道表共用同一套模式：

1. **更新哨兵**：``UNSET`` 用来区分“没提供这个字段”和“把字段清空成 None”；
2. **条件占位**：用一条 ``UPDATE ... WHERE id=? AND status IN (...)`` 原子地把资源
   推进到“执行中”，``rowcount == 0`` 就说明有人抢先或状态不允许——比进程内锁更
   可靠，因为它对多进程/多副本同样成立；
3. **中断恢复**：服务重启后把“执行中”的行标记为失败，避免前端永远停在进度条。

这里只封装 SQL 形状，不掺业务状态名：状态集合与错误码由调用方传入。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

__all__ = [
    "UNSET",
    "Unset",
    "conditional_acquire",
    "mark_interrupted",
    "utcnow",
]


class Unset:
    """显式区分“未提供该字段”与“把该字段置空”（``None`` 表示置空）。"""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


#: ``update_*`` 方法的哨兵值
UNSET = Unset()


def utcnow() -> datetime:
    return datetime.now(UTC)


def conditional_acquire(
    session: Session,
    *,
    model: Any,
    record_id: str,
    allowed_statuses: frozenset[str],
    values: dict[str, Any],
) -> bool:
    """把资源原子推进到"执行中"。

    返回 ``False`` 表示状态已变（被抢先或不允许），调用方应把它翻译成 409，
    **不要**再补一次无条件 update——那会覆盖别人的状态。
    """
    result = session.execute(
        update(model)
        .where(model.id == record_id, model.status.in_(allowed_statuses))
        .values(**values)
    )
    session.commit()
    return bool(result.rowcount)


def mark_interrupted(
    session: Session,
    *,
    model: Any,
    active_statuses: frozenset[str],
    values: dict[str, Any],
) -> int:
    """把``active_statuses``里的行统一改成``values``，返回受影响行数。"""
    result = session.execute(
        update(model).where(model.status.in_(active_statuses)).values(**values)
    )
    session.commit()
    return int(result.rowcount or 0)
