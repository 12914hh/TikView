"""飞书电子表格读写。只使用官方开放接口。"""

from __future__ import annotations

import json
from urllib.parse import quote

import requests

HOST = "https://open.feishu.cn"


class FeishuError(RuntimeError):
    pass


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str, spreadsheet_token: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.spreadsheet_token = spreadsheet_token
        self._access_token = ""

    def list_sheets(self) -> list[dict]:
        url = f"{HOST}/open-apis/sheets/v3/spreadsheets/{self.spreadsheet_token}/sheets/query"
        data = self._request("GET", url)
        return data.get("sheets") or []

    def read_header(self, sheet_id: str) -> list:
        values = self._read_range(f"{sheet_id}!A1:AZ1")
        if not values:
            return []
        return values[0]

    def read_rows(self, sheet_id: str, page_size: int = 200) -> list[list]:
        rows: list[list] = []
        start = 1
        while start <= 5000:
            end = start + page_size - 1
            values = self._read_range(f"{sheet_id}!A{start}:AZ{end}")
            if not values or all(_row_empty(row) for row in values):
                break
            rows.extend(values)
            if len(values) < page_size:
                break
            start += page_size
        while rows and _row_empty(rows[-1]):
            rows.pop()
        return rows

    def write_cell(self, sheet_id: str, column: str, row_number: int, text: str) -> None:
        self.write_cells([(sheet_id, column, row_number, text)])

    def add_sheet(self, title: str) -> str:
        url = f"{HOST}/open-apis/sheets/v2/spreadsheets/{self.spreadsheet_token}/sheets_batch_update"
        data = self._request(
            "POST",
            url,
            json={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        )
        replies = data.get("replies") or []
        properties = ((replies[0].get("addSheet") or {}).get("properties") or {}) if replies else {}
        sheet_id = properties.get("sheetId") or ""
        if not sheet_id:
            raise FeishuError(f"创建工作表「{title}」失败。")
        return sheet_id

    def write_cells(self, updates: list[tuple[str, str, int, str]]) -> None:
        if not updates:
            return
        url = f"{HOST}/open-apis/sheets/v2/spreadsheets/{self.spreadsheet_token}/values_batch_update"
        for start in range(0, len(updates), 50):
            chunk = updates[start : start + 50]
            value_ranges = []
            for sheet_id, column, row_number, text in chunk:
                cell = f"{column}{row_number}"
                value_ranges.append(
                    {
                        "range": f"{sheet_id}!{cell}:{cell}",
                        "values": [[text]],
                    }
                )
            self._request("POST", url, json={"valueRanges": value_ranges})

    def _read_range(self, range_name: str) -> list[list]:
        encoded = quote(range_name, safe="")
        url = (
            f"{HOST}/open-apis/sheets/v2/spreadsheets/"
            f"{self.spreadsheet_token}/values/{encoded}"
        )
        data = self._request("GET", url)
        value_range = data.get("valueRange") or {}
        return value_range.get("values") or []

    def _request(self, method: str, url: str, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token()}"
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise FeishuError(f"飞书返回的不是 JSON，HTTP {response.status_code}") from exc
        if response.status_code >= 400 or body.get("code") not in (0, None):
            code = body.get("code")
            msg = body.get("msg") or response.text[:300]
            raise FeishuError(f"飞书接口失败 code={code} {msg}")
        return body.get("data") or {}

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        response = requests.post(
            f"{HOST}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=30,
        )
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise FeishuError("获取飞书凭证失败：返回的不是 JSON") from exc
        token = body.get("tenant_access_token")
        if body.get("code") not in (0, None) or not token:
            raise FeishuError(f"获取飞书凭证失败：{body.get('msg') or body}")
        self._access_token = token
        return token


def column_letter(index: int) -> str:
    """1-based 列号转 Excel 列名。"""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, list):
        return "".join(cell_text(item) for item in value).strip()
    if isinstance(value, dict):
        for key in ("text", "link", "name"):
            if value.get(key):
                return cell_text(value[key])
        return ""
    return str(value).strip()


def _row_empty(row: list) -> bool:
    return all(cell_text(cell) == "" for cell in row)
