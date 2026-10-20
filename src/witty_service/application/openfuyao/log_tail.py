"""Bootstrap 日志的字节游标读取。

日志是追加写的，用**字节偏移**而不是行号定位：行号会随追加漂移，字节偏移是绝对
位置。只返回**完整行**（半行留给下次），否则 UI 会看到截断的半条命令输出。

阶段 2/3 的 cluster/app 日志直接复用本模块：每个资源一个 ``.log``，
配合各自的 ``/logs`` 端点即可。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_CHUNK_BYTES",
    "LogPage",
    "read_log_page",
    "truncate_log",
]

#: 单次读取上限；调用方可通过 API 的 limit_bytes 覆盖（1KiB ~ 1MiB）
DEFAULT_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class LogPage:
    cursor: int
    next_cursor: int
    lines: list[str] = field(default_factory=list)
    eof: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor,
            "next_cursor": self.next_cursor,
            "lines": self.lines,
            "eof": self.eof,
        }


def truncate_log(path: Path) -> None:
    """每次重跑前清空日志；调用方必须同时把读游标归零，否则会读到旧偏移。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def read_log_page(
    path: Path,
    *,
    cursor: int = 0,
    limit_bytes: int = DEFAULT_CHUNK_BYTES,
) -> LogPage:
    """从 ``cursor`` 字节处读一页完整行。

    - 文件不存在 / 被清空 → 返回空页且 ``eof=True``（不抛错，前端会继续轮询）；
    - ``next_cursor`` 只前进到最后一个换行符，保证返回的都是完整行；
    - ``eof`` 是“本次读到的位置已到文件末尾”，不是“进程结束”。
    """
    start = max(0, cursor)
    if not path.exists():
        return LogPage(cursor=cursor, next_cursor=start, lines=[], eof=True)

    with path.open("rb") as handle:
        handle.seek(start)
        chunk = handle.read(max(1, limit_bytes))
    size = path.stat().st_size

    end = chunk.rfind(b"\n") + 1
    complete = chunk[:end]
    lines = complete.decode("utf-8", errors="replace").splitlines()
    next_cursor = start + end
    return LogPage(
        cursor=cursor,
        next_cursor=next_cursor,
        lines=lines,
        eof=next_cursor >= size,
    )
