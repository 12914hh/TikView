"""TikTok Login Kit。只走官方授权，不访问公开网页。"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
LIST_URL = "https://open.tiktokapis.com/v2/video/list/"
SCOPES = "user.info.basic,video.list"


class TikTokError(RuntimeError):
    pass


class TokenStore:
    """按 open_id 保存多个作者的授权。兼容旧版单对象 tokens.json。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.authors: dict[str, dict] = {}
        if path.exists():
            self.authors = _normalize_store(json.loads(path.read_text(encoding="utf-8")))

    def list_authors(self) -> list[dict]:
        return list(self.authors.values())

    def upsert(self, token: dict, author_id: str = "") -> dict:
        open_id = token["open_id"]
        previous = self.authors.get(open_id) or {}
        record = {
            "open_id": open_id,
            "author_id": author_id or previous.get("author_id", ""),
            "scope": token.get("scope", ""),
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token", ""),
            "expires_at": _expires_at(token.get("expires_in")),
            "refresh_expires_at": _expires_at(token.get("refresh_expires_in")),
            "video_ids": previous.get("video_ids") or [],
            "status": "已授权",
        }
        self.authors[open_id] = record
        self.save()
        return record

    def save(self) -> None:
        payload = {"authors": self.authors}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def refresh_if_needed(self, record: dict, client_key: str, client_secret: str) -> dict:
        expires_at = int(record.get("expires_at") or 0)
        if expires_at and expires_at > int(time.time()) + 300:
            return record
        refresh_token = record.get("refresh_token") or ""
        if not refresh_token:
            raise TikTokError("没有 refresh_token，需要重新授权。")
        refreshed = refresh_access_token(client_key, client_secret, refresh_token)
        record.update(
            {
                "access_token": refreshed["access_token"],
                "refresh_token": refreshed.get("refresh_token") or refresh_token,
                "scope": refreshed.get("scope") or record.get("scope", ""),
                "expires_at": _expires_at(refreshed.get("expires_in")),
                "refresh_expires_at": _expires_at(refreshed.get("refresh_expires_in")),
                "status": "已授权",
            }
        )
        self.authors[record["open_id"]] = record
        self.save()
        return record

    def mark_expired(self, open_id: str) -> dict:
        record = self.authors[open_id]
        record["status"] = "已过期"
        self.save()
        return record


def authorization_url(client_key: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_key": client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def code_from_callback(callback: str, expected_state: str) -> str:
    parsed = urlparse(callback.strip())
    query = parse_qs(parsed.query)
    error = _one(query, "error")
    if error:
        detail = _one(query, "error_description") or error
        raise TikTokError(f"授权没有完成：{detail}")
    state = _one(query, "state")
    if not state or state != expected_state:
        raise TikTokError("回调里的 state 对不上。请重新运行 python auth.py，不要用旧链接。")
    code = _one(query, "code")
    if not code:
        raise TikTokError("这个地址里没有授权码。请复制浏览器地址栏的完整地址。")
    return code


def exchange_code(client_key: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        timeout=30,
    )
    return _token_body(response)


def refresh_access_token(client_key: str, client_secret: str, refresh_token: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        timeout=30,
    )
    return _token_body(response)


def list_view_counts(access_token: str) -> dict[str, int]:
    """返回该授权账号公开视频的播放量。键是视频 ID。"""
    counts: dict[str, int] = {}
    cursor = None
    for _ in range(50):
        payload: dict = {"max_count": 20}
        if cursor is not None:
            payload["cursor"] = cursor
        response = requests.post(
            LIST_URL,
            params={"fields": "id,view_count"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise TikTokError(f"TikTok 返回的不是 JSON，HTTP {response.status_code}") from exc
        error = body.get("error") or {}
        if error.get("code") not in (None, "ok"):
            message = error.get("message") or error.get("code") or response.text[:200]
            raise TikTokError(f"读取视频失败：{message}")
        data = body.get("data") or {}
        for video in data.get("videos") or []:
            video_id = str(video.get("id") or "").strip()
            if video_id and video.get("view_count") is not None:
                counts[video_id] = int(video["view_count"])
        if not data.get("has_more"):
            break
        cursor = data.get("cursor")
        if cursor is None:
            break
    return counts


def _normalize_store(raw) -> dict[str, dict]:
    if isinstance(raw, dict) and isinstance(raw.get("authors"), dict):
        return {open_id: dict(record) for open_id, record in raw["authors"].items()}
    if isinstance(raw, dict) and raw.get("access_token") and raw.get("open_id"):
        open_id = raw["open_id"]
        return {
            open_id: {
                "open_id": open_id,
                "author_id": raw.get("author_id", ""),
                "scope": raw.get("scope", ""),
                "access_token": raw["access_token"],
                "refresh_token": raw.get("refresh_token", ""),
                "expires_at": _expires_at(raw.get("expires_in")),
                "refresh_expires_at": _expires_at(raw.get("refresh_expires_in")),
                "video_ids": raw.get("video_ids") or [],
                "status": "已授权",
            }
        }
    return {}


def _expires_at(expires_in) -> int:
    try:
        seconds = int(expires_in or 0)
    except (TypeError, ValueError):
        return 0
    if seconds <= 0:
        return 0
    return int(time.time()) + seconds


def _token_body(response: requests.Response) -> dict:
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise TikTokError(f"TikTok 返回的不是 JSON，HTTP {response.status_code}") from exc
    if body.get("error"):
        raise TikTokError(body.get("error_description") or body.get("error"))
    if not body.get("access_token") or not body.get("open_id"):
        raise TikTokError("TikTok 没有返回 access_token。确认 Client key 和 Redirect URI 与后台一致。")
    return {
        "open_id": body["open_id"],
        "scope": body.get("scope", ""),
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token", ""),
        "expires_in": body.get("expires_in"),
        "refresh_expires_in": body.get("refresh_expires_in"),
    }


def _one(query: dict, name: str) -> str:
    values = query.get(name) or []
    return values[0] if values else ""
