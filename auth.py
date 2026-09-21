"""生成 TikTok 授权链接，并用回调地址换取 token。支持多个作者。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from tiktok import (
    TikTokError,
    TokenStore,
    authorization_url,
    code_from_callback,
    exchange_code,
    new_state,
)

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".auth_state"
TOKEN_PATH = ROOT / "tokens.json"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="用 TikTok Login Kit 给一个作者授权")
    parser.add_argument(
        "--author",
        help="飞书表「ID」列里的作者标识。过期时按这个作者打标",
    )
    parser.add_argument("--callback", help="授权完成后浏览器地址栏的完整地址")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    try:
        client_key = _env("TIKTOK_CLIENT_KEY")
        client_secret = _env("TIKTOK_CLIENT_SECRET")
        redirect_uri = _env("TIKTOK_REDIRECT_URI")
        store = TokenStore(TOKEN_PATH)
        if args.callback:
            pending = _load_pending()
            code = code_from_callback(args.callback, pending["state"])
            token = exchange_code(client_key, client_secret, code, redirect_uri)
            author_id = args.author or pending.get("author_id") or ""
            record = store.upsert(token, author_id=author_id)
            STATE_PATH.unlink(missing_ok=True)
        else:
            state = new_state()
            _save_pending(state, args.author or "")
    except TikTokError as exc:
        print(exc)
        return 1
    except OSError as exc:
        print(f"读写本机授权文件失败：{exc}")
        return 1

    if args.callback:
        scopes = record.get("scope") or "未返回"
        print(f"授权已保存。当前共 {len(store.list_authors())} 个作者。")
        print(f"open_id 已记录，scope = {scopes}")
        if record.get("author_id"):
            print(f"已绑定飞书作者 ID：{record['author_id']}")
        else:
            print("还没有绑定飞书作者 ID。下次可用：python auth.py --author 表里的作者ID")
        if "video.list" not in scopes:
            print("这次同意的权限里没有 video.list。请重新授权，并在页面上允许读取公开视频。")
        return 0

    print(authorization_url(client_key, redirect_uri, state))
    if args.author:
        print(f"这次授权会绑定飞书作者 ID：{args.author}")
    print("用准备授权的 TikTok 账号打开上面的链接。同意后，复制地址栏的完整地址，再运行：")
    if args.author:
        print(f'python auth.py --author {args.author} --callback "粘贴的地址"')
    else:
        print('python auth.py --callback "粘贴的地址"')
    return 0


def _save_pending(state: str, author_id: str) -> None:
    STATE_PATH.write_text(
        json.dumps({"state": state, "author_id": author_id}, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_pending() -> dict:
    raw = STATE_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        raise TikTokError("没有找到本次授权的 state。请先运行 python auth.py。")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"state": raw, "author_id": ""}
    if not data.get("state"):
        raise TikTokError("没有找到本次授权的 state。请先运行 python auth.py。")
    return data


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise TikTokError(f"缺少 {name}。把它写进 .env，不要发到对话里。")
    return value


if __name__ == "__main__":
    sys.exit(main())
