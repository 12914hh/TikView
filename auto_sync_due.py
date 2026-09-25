"""GitHub / 服务器定时用。开关打开后，到点或晚点补跑都会执行。"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # GitHub 定时步骤还没装依赖；密钥已由 Actions 注入环境变量
    def load_dotenv(*_args, **_kwargs):
        return False

from schedule_conf import load_schedule

BEIJING = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent


def main() -> int:
    load_dotenv(ROOT / ".env")
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    # 只有网页上点 Run workflow 才强制跑；定时都走到点或补跑判断
    force = event == "workflow_dispatch"
    schedule = load_schedule()
    now = datetime.now(BEIJING)
    today = now.strftime("%Y-%m-%d")
    # 上次运行可能是 YYYY-MM-DD 或 YYYY-MM-DD HH:00，补跑只比日期
    last_run_day = (schedule.last_run or "").strip()[:10]
    weekday_ok = now.isoweekday() == schedule.weekday
    on_hour = weekday_ok and now.hour == schedule.hour
    catch_up = weekday_ok and now.hour > schedule.hour and last_run_day != today
    due = schedule.enabled and (force or on_hour or catch_up)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"due={'true' if due else 'false'}\n")
    if not schedule.enabled:
        result = "定时任务已停止，本次跳过。"
    elif due and force:
        result = "手动触发，本次执行。"
    elif due and on_hour:
        result = "到点，本次执行。"
    elif due and catch_up:
        result = f"已过设定时间且今日未跑过（上次 {schedule.last_run or '无'}），本次补跑。"
    else:
        result = f"本次跳过（事件 {event or '未知'}）。"
    print(
        f"北京时间 {now:%Y-%m-%d %H:%M}，{schedule.when()}，"
        f"{schedule.status()}，来源 {schedule.source}，{result}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
