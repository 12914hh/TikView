"""同步所有已授权作者的播放量到飞书。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from feishu import FeishuError, cell_text, column_letter
from sync import ROOT, _business_client, _cell, _env, _load_sheet, _locate_columns, _tikview_client
from tiktok import TikTokError, TokenStore, list_view_counts
from tokens_sheet import load_auth_records, upsert_auth_record

TOKEN_PATH = ROOT / "tokens.json"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="把已授权作者的播放量写回飞书")
    parser.add_argument("--write", action="store_true", help="写回表格。不加则只预览")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    try:
        client = _business_client()
        tikview = _tikview_client()
        store = TokenStore(TOKEN_PATH)
        authors = {item["open_id"]: item for item in store.list_authors()}
        for item in load_auth_records(tikview):
            authors[item["open_id"]] = item
        author_list = list(authors.values())
        if not author_list:
            raise TikTokError("还没有授权记录。先在窗口里生成链接，让作者点同意。")
        sheet, rows = _load_sheet(client)
    except (TikTokError, FeishuError) as exc:
        print(exc)
        return 1

    headers = [cell_text(cell) for cell in rows[0]]
    located = _locate_columns({name: index for index, name in enumerate(headers) if name})
    if "视频ID" not in located or "播放量(K)" not in located:
        print("表里没有「视频ID」或「播放量（K）」列。")
        return 1

    video_index = located["视频ID"][1]
    views_index = located["播放量(K)"][1]
    track_index = located.get("追踪", (None, None))[1]
    author_index = located.get("ID", (None, None))[1]

    sheet_rows = []
    for row_number, row in enumerate(rows[1:], start=2):
        video_id = _cell(row, video_index)
        tracked = track_index is None or _cell(row, track_index) != "否"
        author_id = _cell(row, author_index) if author_index is not None else ""
        if not video_id and not author_id:
            continue
        sheet_rows.append(
            {
                "row": row_number,
                "video_id": video_id,
                "old_views": _cell(row, views_index),
                "author_id": author_id,
                "tracked": tracked,
            }
        )

    client_key = _env("TIKTOK_CLIENT_KEY")
    client_secret = _env("TIKTOK_CLIENT_SECRET")
    updates: list[tuple[str, str, int, str]] = []
    success = 0
    expired = 0
    skipped = 0
    unmatched_videos = 0
    succeeded_authors: list[str] = []
    failed_authors: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"已保存授权：{len(author_list)} 个作者")
    print(f"表里有视频 ID 的行：{len(sheet_rows)}")

    for record in author_list:
        label = record.get("author_id") or record["open_id"][:8]
        try:
            record = store.refresh_if_needed(record, client_key, client_secret)
            counts = list_view_counts(record["access_token"])
            record["video_ids"] = list(counts)
            record["status"] = "已授权"
            store.authors[record["open_id"]] = record
            store.save()
            if args.write:
                upsert_auth_record(tikview, record)
        except TikTokError as exc:
            print(f"[{label}] 授权不可用：{exc}")
            if record.get("open_id") in store.authors:
                store.mark_expired(record["open_id"])
            record["status"] = "已过期"
            if args.write:
                upsert_auth_record(tikview, record)
            expired_rows = _rows_for_expired(sheet_rows, record)
            if args.write:
                updates.extend(_expire_updates(sheet["sheet_id"], located, expired_rows, now))
            expired += len(expired_rows)
            failed_authors.append(label)
            print(f"[{label}] 将标记已过期：{len(expired_rows)} 行")
            continue

        matched_rows = set()
        matched = 0
        for item in sheet_rows:
            if not item["video_id"] or item["video_id"] not in counts:
                continue
            if not item["tracked"]:
                skipped += 1
                continue
            matched += 1
            matched_rows.add(item["row"])
            success += 1
            new_views = format_views(counts[item["video_id"]])
            print(
                f"[{label}] 第 {item['row']} 行  "
                f"{item['video_id']}  {item['old_views'] or '空'} -> {new_views}"
            )
            if args.write:
                updates.extend(
                    _success_updates(
                        sheet["sheet_id"],
                        located,
                        item["row"],
                        item["old_views"],
                        new_views,
                        now,
                    )
                )
        author_rows = _rows_for_author(sheet_rows, record.get("author_id") or "")
        auth_only = [item for item in author_rows if item["row"] not in matched_rows]
        if record.get("author_id"):
            print(f"[{label}] 授权状态将标为已授权：{len(author_rows)} 行")
            if args.write:
                updates.extend(_authorize_updates(sheet["sheet_id"], located, auth_only))
        elif matched:
            print(f"[{label}] 这条授权还没绑定作者 ID，只给对上视频的行标已授权。")
        unmatched = len(counts) - matched - sum(
            1 for item in sheet_rows if item["video_id"] in counts and not item["tracked"]
        )
        unmatched_videos += max(unmatched, 0)
        succeeded_authors.append(label)
        print(f"[{label}] 公开视频 {len(counts)} 条，写入候选 {matched} 行")

    print(
        f"合计：成功 {success}，过期打标 {expired}，追踪跳过 {skipped}，"
        f"账号有但表里没有的视频约 {unmatched_videos}"
    )
    summary = _summary(_clock(), succeeded_authors, failed_authors, success)
    if not args.write:
        print("这次没有改表格。确认后运行：python pull.py --write")
        return 0

    try:
        client.write_cells(updates)
    except FeishuError as exc:
        print(exc)
        _notify_bot(_summary(_clock(), succeeded_authors, failed_authors, success, str(exc)))
        return 1
    print(f"已写回 {len(updates)} 个单元格。")
    _notify_bot(summary)
    return 0


def _clock() -> str:
    return "【" + datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M") + "】"


def _summary(clock: str, succeeded: list[str], failed: list[str], video_rows: int, write_error: str = "") -> str:
    lines = [
        "**【TikView 系统通知】**",
        f"🕐 **播放量更新时间：**{clock}",
        f"✅ **成功：**{len(succeeded)}人",
        f"❌ **失败：**{len(failed)}人",
    ]
    if failed:
        lines.append("👤 **失败作者：**" + ",".join(f"【{name}】" for name in failed))
    lines.append(f"📋 **结果：**已写入 {video_rows} 行")
    if write_error:
        lines.append(f"🔴 **写入失败：**{write_error}")
    return "\n".join(lines)


def _notify_bot(text: str) -> None:
    chat_id = os.environ.get("FEISHU_CHAT_ID", "").strip()
    if not chat_id:
        print("未配置 FEISHU_CHAT_ID，跳过飞书通知。")
        return
    try:
        token = _tenant_token()
        response = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(
                    {
                        "config": {"wide_screen_mode": True},
                        "elements": [{"tag": "markdown", "content": text}],
                    },
                    ensure_ascii=False,
                ),
            },
            timeout=15,
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"飞书通知发送失败：{exc}")
        return
    if body.get("code") not in (0, None):
        print(f"飞书通知发送失败：{body.get('msg') or body.get('code')}")
        return
    print("已发送飞书通知。")


def _tenant_token() -> str:
    response = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": os.environ["FEISHU_APP_ID"],
            "app_secret": os.environ["FEISHU_APP_SECRET"],
        },
        timeout=15,
    )
    token = response.json().get("tenant_access_token")
    if not token:
        raise requests.RequestException(response.json().get("msg") or "获取飞书凭证失败")
    return token


def format_views(count: int) -> str:
    if count < 1000:
        return str(count)
    return f"{(count + 500) // 1000}K"


def _rows_for_author(sheet_rows: list[dict], author_id: str) -> list[dict]:
    if not author_id:
        return []
    return [item for item in sheet_rows if item["tracked"] and item["author_id"] == author_id]


def _rows_for_expired(sheet_rows: list[dict], record: dict) -> list[dict]:
    author_rows = _rows_for_author(sheet_rows, record.get("author_id") or "")
    if author_rows:
        return author_rows
    video_ids = set(record.get("video_ids") or [])
    return [
        item
        for item in sheet_rows
        if item["tracked"] and item["video_id"] in video_ids
    ]


def _authorize_updates(sheet_id, located, rows):
    updates = []
    for item in rows:
        updates.extend(
            _field_updates(sheet_id, located, item["row"], {"授权状态": "已授权"})
        )
    return updates


def _success_updates(sheet_id, located, row_number, old, new_views, now):
    fields = {
        "播放量(K)": new_views,
        "同步状态": "成功",
        "授权状态": "已授权",
        "更新时间": now,
        "失败原因": "",
    }
    if "上次播放量(K)" in located and old:
        fields["上次播放量(K)"] = old
    return _field_updates(sheet_id, located, row_number, fields)


def _expire_updates(sheet_id, located, rows, now):
    updates = []
    for item in rows:
        updates.extend(
            _field_updates(
                sheet_id,
                located,
                item["row"],
                {
                    "授权状态": "已过期",
                    "同步状态": "失败",
                    "失败原因": "授权过期",
                    "更新时间": now,
                },
            )
        )
    return updates


def _field_updates(sheet_id, located, row_number, fields: dict[str, str]):
    updates = []
    for name, value in fields.items():
        found = located.get(name)
        if not found:
            continue
        updates.append((sheet_id, column_letter(found[1] + 1), row_number, value))
    return updates


if __name__ == "__main__":
    sys.exit(main())
