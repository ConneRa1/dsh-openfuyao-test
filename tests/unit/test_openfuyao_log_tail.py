"""字节游标日志读取：只返回完整行、游标只前进、截断后可重读。"""

from __future__ import annotations

from pathlib import Path

from witty_service.application.openfuyao.log_tail import (
    LogPage,
    read_log_page,
    truncate_log,
)


def test_missing_file_is_an_empty_page(tmp_path: Path) -> None:
    page = read_log_page(tmp_path / "nope.log")

    assert page.lines == []
    assert page.eof is True
    assert page.next_cursor == 0


def test_reads_only_complete_lines(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("first\nsecond\nin-progress", encoding="utf-8")

    page = read_log_page(path)

    assert page.lines == ["first", "second"]
    assert page.next_cursor == len("first\nsecond\n")
    assert page.eof is False


def test_cursor_advances_without_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("one\n", encoding="utf-8")
    first = read_log_page(path)

    with path.open("a", encoding="utf-8") as handle:
        handle.write("two\n")
    second = read_log_page(path, cursor=first.next_cursor)

    assert first.lines == ["one"]
    assert second.lines == ["two"]
    assert second.eof is True


def test_limit_bytes_keeps_line_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("12345\n67890\n", encoding="utf-8")

    page = read_log_page(path, limit_bytes=7)

    # 7 字节正好覆盖 "12345\n6"，只能返回完整的第一行
    assert page.lines == ["12345"]
    assert page.eof is False


def test_partial_line_is_never_returned(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("cut", encoding="utf-8")

    page = read_log_page(path)

    assert page.lines == []
    assert page.next_cursor == 0


def test_invalid_utf8_is_replaced_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_bytes(b"ok\n\xff\xfe\n")

    page = read_log_page(path)

    assert page.lines[0] == "ok"
    assert len(page.lines) == 2


def test_truncate_log_resets_content_and_cursor(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("old\n", encoding="utf-8")
    first = read_log_page(path)
    assert first.lines == ["old"]

    truncate_log(path)
    path.write_text("new\n", encoding="utf-8")

    # 重跑必须从 0 读，否则会停在旧偏移
    page = read_log_page(path, cursor=0)
    assert page.lines == ["new"]
    assert page.eof is True


def test_truncate_log_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "env-1" / "bootstrap.log"

    truncate_log(path)

    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_page_serializes_for_the_api(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("hello\n", encoding="utf-8")

    payload = read_log_page(path).to_dict()

    assert set(payload) == {"cursor", "next_cursor", "lines", "eof"}
    assert isinstance(read_log_page(path), LogPage)
