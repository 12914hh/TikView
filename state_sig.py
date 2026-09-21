"""授权链接里的 state。本地和 Cloudflare Worker 用同一套算法。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def sign_state(secret: str, author_id: str, now: int | None = None) -> str:
    payload = _b64(json.dumps({"a": author_id, "t": int(now if now is not None else time.time())}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_state(secret: str, state: str, max_age: int = 24 * 3600) -> dict:
    payload, dot, signature = state.partition(".")
    if not dot or not payload or not signature:
        raise ValueError("授权链接无效")
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise ValueError("授权链接校验失败")
    data = json.loads(_unb64(payload))
    issued = int(data.get("t") or 0)
    if issued <= 0 or int(time.time()) - issued > max_age:
        raise ValueError("授权链接已过期，请重新生成")
    if not str(data.get("a") or "").strip():
        raise ValueError("授权链接里没有作者 ID")
    return data


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)
