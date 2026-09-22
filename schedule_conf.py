"""自动更新时间：飞书「配置」表。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
CONFIG_TITLE = "配置"
DEFAULT_WEEKDAY = 1
DEFAULT_HOUR = 10
HOST = "https://open.feishu.cn"
ON_VALUES = {"开", "是", "1", "true", "on", "启用"}


@dataclass
class Schedule:
    weekday: int = DEFAULT_WEEKDAY
    hour: int = DEFAULT_HOUR
    enabled: bool = False
    last_run: str = ""
    source: str = "默认"

    def when(self) -> str:
        return format_schedule(self.weekday, self.hour)

    def status(self) -> str:
        return "已开启" if self.enabled else "已停止"


def validate(weekday: int, hour: int) -> tuple[int, int]:
    if weekday < 1 or weekday > 7:
        raise ValueError("星期要选周一到周日。")
    if hour < 0 or hour > 23:
        raise ValueError("小时要选 0 到 23。")
    return weekday, hour


def format_schedule(weekday: int, hour: int) -> str:
    weekday, hour = validate(weekday, hour)
    return f"每{WEEKDAYS[weekday - 1]} {hour:02d}:00（北京时间）"


def parse_enabled(value: str) -> bool:
    return value.strip().lower() in ON_VALUES


def enabled_text(enabled: bool) -> str:
    return "开" if enabled else "关"


def read_feishu() -> Schedule | None:
    """给 GitHub 定时任务用，只用标准库。读不到就返回 None。"""
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    token = _spreadsheet_token(os.environ.get("FEISHU_TIKVIEW_SPREADSHEET_TOKEN", ""))
    if not app_id or not app_secret or not token:
        return None
    access = _tenant_token(app_id, app_secret)
    sheet_id = _find_sheet_id(access, token, CONFIG_TITLE)
    if not sheet_id:
        return None
    rows = _read_range(access, token, f"{sheet_id}!A1:Z5")
    parsed = _parse_config_rows(rows)
    if parsed is None:
        return None
    parsed.source = "飞书「配置」表"
    return parsed


def write_feishu(schedule: Schedule) -> None:
    weekday, hour = validate(schedule.weekday, schedule.hour)
    from dotenv import load_dotenv

    from feishu import FeishuClient
    from sync import ROOT, _env, _spreadsheet_token as token_from_env

    load_dotenv(ROOT / ".env")
    client = FeishuClient(
        _env("FEISHU_APP_ID"),
        _env("FEISHU_APP_SECRET"),
        token_from_env(_env("FEISHU_TIKVIEW_SPREADSHEET_TOKEN")),
    )
    sheet_id = _ensure_config_sheet(client)
    client.write_cells(
        [
            (sheet_id, "A", 1, "星期"),
            (sheet_id, "B", 1, "小时"),
            (sheet_id, "C", 1, "开关"),
            (sheet_id, "D", 1, "上次运行"),
            (sheet_id, "A", 2, str(weekday)),
            (sheet_id, "B", 2, str(hour)),
            (sheet_id, "C", 2, enabled_text(schedule.enabled)),
            (sheet_id, "D", 2, schedule.last_run or ""),
        ]
    )


def mark_schedule_ran(day: str = "") -> None:
    """更新飞书「配置」表的上次运行日期（北京时间 YYYY-MM-DD）。"""
    from datetime import datetime, timedelta, timezone

    from dotenv import load_dotenv

    from feishu import FeishuClient
    from sync import ROOT, _env, _spreadsheet_token as token_from_env

    if not day:
        day = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    load_dotenv(ROOT / ".env")
    current = load_schedule()
    current.last_run = day
    client = FeishuClient(
        _env("FEISHU_APP_ID"),
        _env("FEISHU_APP_SECRET"),
        token_from_env(_env("FEISHU_TIKVIEW_SPREADSHEET_TOKEN")),
    )
    sheet_id = _ensure_config_sheet(client)
    client.write_cells(
        [
            (sheet_id, "D", 1, "上次运行"),
            (sheet_id, "D", 2, day),
        ]
    )


def load_schedule() -> Schedule:
    try:
        remote = read_feishu()
    except Exception:
        remote = None
    if remote is not None:
        return remote
    return Schedule()


def _parse_config_rows(rows: list[list]) -> Schedule | None:
    if len(rows) < 2:
        return None
    header = [_cell(cell) for cell in rows[0]]
    data = rows[1]
    weekday_index = _header_index(header, "星期", 0)
    hour_index = _header_index(header, "小时", 1)
    enabled_index = _header_index(header, "开关", 2)
    try:
        weekday = int(float(_at(data, weekday_index)))
        hour = int(float(_at(data, hour_index)))
        weekday, hour = validate(weekday, hour)
    except (TypeError, ValueError):
        return None
    enabled = False
    if "开关" in header:
        enabled = parse_enabled(_at(data, enabled_index))
    last_run = ""
    if "上次运行" in header:
        last_run = _at(data, _header_index(header, "上次运行", 3))
    return Schedule(weekday=weekday, hour=hour, enabled=enabled, last_run=last_run)


def _ensure_config_sheet(client) -> str:
    for sheet in client.list_sheets():
        if sheet.get("title") == CONFIG_TITLE:
            return sheet.get("sheet_id") or sheet.get("sheetId") or ""
    sheet_id = client.add_sheet(CONFIG_TITLE)
    client.write_cells(
        [
            (sheet_id, "A", 1, "星期"),
            (sheet_id, "B", 1, "小时"),
            (sheet_id, "C", 1, "开关"),
            (sheet_id, "D", 1, "上次运行"),
        ]
    )
    return sheet_id


def _header_index(header: list[str], name: str, fallback: int) -> int:
    try:
        return header.index(name)
    except ValueError:
        return fallback


def _tenant_token(app_id: str, app_secret: str) -> str:
    body = _http_json(
        "POST",
        f"{HOST}/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = body.get("tenant_access_token")
    if body.get("code") not in (0, None) or not token:
        raise RuntimeError(body.get("msg") or "获取飞书凭证失败")
    return token


def _find_sheet_id(access: str, spreadsheet: str, title: str) -> str:
    body = _http_json(
        "GET",
        f"{HOST}/open-apis/sheets/v3/spreadsheets/{spreadsheet}/sheets/query",
        token=access,
    )
    for sheet in (body.get("data") or {}).get("sheets") or []:
        if sheet.get("title") == title:
            return sheet.get("sheet_id") or sheet.get("sheetId") or ""
    return ""


def _read_range(access: str, spreadsheet: str, range_name: str) -> list[list]:
    encoded = urllib.parse.quote(range_name, safe="")
    body = _http_json(
        "GET",
        f"{HOST}/open-apis/sheets/v2/spreadsheets/{spreadsheet}/values/{encoded}",
        token=access,
    )
    value_range = (body.get("data") or {}).get("valueRange") or {}
    return value_range.get("values") or []


def _http_json(method: str, url: str, payload: dict | None = None, token: str = "") -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"飞书接口失败 HTTP {exc.code} {detail}") from exc
    if body.get("code") not in (0, None):
        raise RuntimeError(body.get("msg") or f"飞书接口失败 code={body.get('code')}")
    return body


def _spreadsheet_token(raw: str) -> str:
    token = (raw or "").strip()
    if "/sheets/" in token:
        token = token.split("/sheets/", 1)[1]
    return token.split("?", 1)[0].split("#", 1)[0].strip("/")


def _at(row: list, index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return _cell(row[index])


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(_cell(item) for item in value).strip()
    if isinstance(value, dict):
        for key in ("text", "link", "name"):
            if value.get(key):
                return _cell(value[key])
        return ""
    return str(value).strip()
