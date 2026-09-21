"""把作者授权存在飞书「授权」表，不写进达人管理表。"""

from __future__ import annotations

from feishu import FeishuClient, cell_text

AUTH_TITLE = "授权"
HEADERS = [
    "作者ID",
    "status",
    "open_id",
    "access_token",
    "refresh_token",
    "expires_at",
    "refresh_expires_at",
    "scope",
    "video_ids",
]


def load_auth_records(client: FeishuClient) -> list[dict]:
    sheet_id = _find_sheet_id(client)
    if not sheet_id:
        return []
    rows = client.read_rows(sheet_id)
    if len(rows) < 2:
        return []
    header = [cell_text(cell) for cell in rows[0]]
    index = {name: i for i, name in enumerate(header)}
    records = []
    for row in rows[1:]:
        open_id = _at(row, index.get("open_id"))
        access_token = _at(row, index.get("access_token"))
        if not open_id or not access_token:
            continue
        video_ids = [item for item in _at(row, index.get("video_ids")).split(",") if item]
        records.append(
            {
                "open_id": open_id,
                "author_id": _at(row, index.get("作者ID")),
                "access_token": access_token,
                "refresh_token": _at(row, index.get("refresh_token")),
                "expires_at": _int(_at(row, index.get("expires_at"))),
                "refresh_expires_at": _int(_at(row, index.get("refresh_expires_at"))),
                "scope": _at(row, index.get("scope")),
                "status": _at(row, index.get("status")) or "已授权",
                "video_ids": video_ids,
            }
        )
    return records


def upsert_auth_record(client: FeishuClient, record: dict) -> None:
    sheet_id = ensure_auth_sheet(client)
    rows = client.read_rows(sheet_id)
    header = [cell_text(cell) for cell in rows[0]] if rows else []
    index = {name: i for i, name in enumerate(header)}
    values = _row_values(record)
    target = None
    first_empty = None
    open_id_index = index.get("open_id", 1)
    for row_number, row in enumerate(rows[1:], start=2):
        open_id = _at(row, open_id_index)
        if open_id == record["open_id"]:
            target = row_number
            break
        if not open_id and first_empty is None:
            first_empty = row_number
    if target is None:
        target = first_empty or max(len(rows), 1) + 1
    client.write_cells(
        [
            (sheet_id, _column(position), target, value)
            for position, value in enumerate(values, start=1)
        ]
    )


def ensure_auth_sheet(client: FeishuClient) -> str:
    sheet_id = _find_sheet_id(client)
    if sheet_id:
        return sheet_id
    sheet_id = client.add_sheet(AUTH_TITLE)
    client.write_cells(
        [(sheet_id, _column(position), 1, name) for position, name in enumerate(HEADERS, start=1)]
    )
    return sheet_id


def _find_sheet_id(client: FeishuClient) -> str:
    for sheet in client.list_sheets():
        if sheet.get("title") == AUTH_TITLE:
            return sheet.get("sheet_id") or ""
    return ""


def _row_values(record: dict) -> list[str]:
    return [
        record.get("author_id") or "",
        record.get("status") or "",
        record.get("open_id") or "",
        record.get("access_token") or "",
        record.get("refresh_token") or "",
        str(record.get("expires_at") or ""),
        str(record.get("refresh_expires_at") or ""),
        record.get("scope") or "",
        ",".join(record.get("video_ids") or []),
    ]


def _at(row: list, index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return cell_text(row[index])


def _int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _column(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
