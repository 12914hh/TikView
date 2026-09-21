"""读飞书表并核对列名。加上 --write 时，只在第一行可追踪视频上试写「同步状态」。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from feishu import FeishuClient, FeishuError, cell_text, column_letter


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = project_root()
REQUIRED_HEADERS = ("视频ID", "同步状态")
COLUMN_ALIASES = {
    "失败原因": ("失败原因", "失败原图"),
    "上次播放量(K)": ("上次播放量(K)",),
    "播放量(K)": ("播放量(K)",),
}
TEST_STATUS = "试写成功"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="读取飞书合作表，可选试写一格同步状态")
    parser.add_argument(
        "--write",
        action="store_true",
        help="向第一行可追踪视频的「同步状态」写入「试写成功」",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    try:
        client = FeishuClient(
            _env("FEISHU_APP_ID"),
            _env("FEISHU_APP_SECRET"),
            _spreadsheet_token(_env("FEISHU_SPREADSHEET_TOKEN")),
        )
        sheet, rows = _load_sheet(client)
    except FeishuError as exc:
        print(exc)
        _print_permission_hint(str(exc))
        return 1

    if not rows:
        print(f"工作表「{sheet['title']}」是空的。")
        return 1

    headers = [cell_text(cell) for cell in rows[0]]
    columns = {name: index for index, name in enumerate(headers) if name}
    located = _locate_columns(columns)
    missing = [name for name in REQUIRED_HEADERS if name not in located]
    if missing:
        print(f"工作表「{sheet['title']}」表头缺少：" + "、".join(missing))
        print("当前读到的表头：" + "、".join(name for name in headers if name))
        return 1

    track_index = located.get("追踪", (None, None))[1]
    video_index = located["视频ID"][1]
    eligible: list[int] = []
    skipped = 0
    for offset, row in enumerate(rows[1:], start=2):
        if _cell(row, video_index) == "":
            continue
        if track_index is not None and _cell(row, track_index) == "否":
            skipped += 1
            continue
        eligible.append(offset)

    print(f"工作表：{sheet['title']}")
    print("列位置：" + "，".join(
        f"{actual}={column_letter(index + 1)}"
        for actual, index in located.values()
    ))
    print(f"有视频 ID 且未取消追踪：{len(eligible)} 行")
    print(f"追踪填了「否」：{skipped} 行")

    if not eligible:
        print("没有可试写的行。确认「视频ID」列有值，且「追踪」不是「否」。")
        return 1

    target_row = eligible[0]
    status_column = column_letter(located["同步状态"][1] + 1)
    print(f"试写目标：{status_column}{target_row}")
    if not args.write:
        print("这次没有改表格。确认上面的列位置无误后，再运行：python sync.py --write")
        return 0

    try:
        client.write_cell(sheet["sheet_id"], status_column, target_row, TEST_STATUS)
    except FeishuError as exc:
        print(exc)
        _print_permission_hint(str(exc))
        return 1

    print(f"已写入 {status_column}{target_row} = {TEST_STATUS}")
    return 0


def _locate_columns(columns: dict[str, int]) -> dict[str, tuple[str, int]]:
    """按逻辑列名找到表头。全角括号与半角括号视为相同。"""
    normalized = {_norm_header(name): (name, index) for name, index in columns.items()}
    found: dict[str, tuple[str, int]] = {}
    for name in ("视频ID", "同步状态", "追踪", "授权状态", "更新时间", "播放量(K)", "ID"):
        hit = normalized.get(_norm_header(name))
        if hit:
            found[name] = hit
    for name, aliases in COLUMN_ALIASES.items():
        if name in found:
            continue
        for alias in aliases:
            hit = normalized.get(_norm_header(alias))
            if hit:
                found[name] = hit
                break
    return found


def _norm_header(name: str) -> str:
    return (
        name.replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
        .strip()
    )


def _load_sheet(client: FeishuClient) -> tuple[dict, list]:
    sheets = client.list_sheets()
    if not sheets:
        raise FeishuError("这个表格里没有工作表。")

    explicit = _explicit_sheet(sheets)
    if explicit is not None:
        return explicit, client.read_rows(explicit["sheet_id"])

    matches = _sheets_with_header(client, sheets, "视频ID")
    if not matches:
        names = "、".join(sheet.get("title") or "" for sheet in sheets)
        raise FeishuError(
            "没有找到带「视频ID」的工作表。"
            f"当前文件里的工作表是：{names}。"
            "请把 .env 里的表格链接换成达人合作那一份；"
            "如果就在这个文件里，把工作表名称填到 FEISHU_SHEET_TITLE。"
        )
    if len(matches) > 1:
        titles = "、".join(sheet.get("title") or "" for sheet in matches)
        raise FeishuError(f"有多张工作表都有「视频ID」：{titles}。请在 .env 设置 FEISHU_SHEET_TITLE。")
    sheet = matches[0]
    return sheet, client.read_rows(sheet["sheet_id"])


def _explicit_sheet(sheets: list[dict]) -> dict | None:
    wanted_id = os.environ.get("FEISHU_SHEET_ID", "").strip()
    wanted_title = os.environ.get("FEISHU_SHEET_TITLE", "").strip()
    if not wanted_id and not wanted_title:
        return None
    for sheet in sheets:
        if wanted_id and sheet.get("sheet_id") == wanted_id:
            return sheet
        if wanted_title and sheet.get("title") == wanted_title:
            return sheet
    names = "、".join(sheet.get("title") or "" for sheet in sheets)
    raise FeishuError(f"没有找到指定工作表。现有工作表：{names}")


def _sheets_with_header(client: FeishuClient, sheets: list[dict], header: str) -> list[dict]:
    found = []
    for sheet in sheets:
        if sheet.get("hidden"):
            continue
        names = {cell_text(cell) for cell in client.read_header(sheet["sheet_id"])}
        if header in names:
            found.append(sheet)
    return found


def _cell(row: list, index: int) -> str:
    if index >= len(row):
        return ""
    return cell_text(row[index])


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise FeishuError(
            f"缺少 {name}。把 .env.example 复制为 .env，填入飞书应用凭证和表格 token。"
        )
    return value


def _business_client() -> FeishuClient:
    return FeishuClient(
        _env("FEISHU_APP_ID"),
        _env("FEISHU_APP_SECRET"),
        _spreadsheet_token(_env("FEISHU_SPREADSHEET_TOKEN")),
    )


def _tikview_client() -> FeishuClient:
    return FeishuClient(
        _env("FEISHU_APP_ID"),
        _env("FEISHU_APP_SECRET"),
        _spreadsheet_token(_env("FEISHU_TIKVIEW_SPREADSHEET_TOKEN")),
    )


def _spreadsheet_token(raw: str) -> str:
    token = raw.strip()
    if "/sheets/" in token:
        token = token.split("/sheets/", 1)[1]
    return token.split("?", 1)[0].split("#", 1)[0].strip("/")


def _print_permission_hint(message: str) -> None:
    if "403" in message or "99991672" in message or "权限" in message:
        print("请确认：应用已发布，电子表格权限已开通，并且应用已是这张表的可编辑协作者。")


if __name__ == "__main__":
    sys.exit(main())
