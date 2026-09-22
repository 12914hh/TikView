"""GitHub 定时任务用。开关打开后，到点或晚点补跑都会执行。"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from schedule_conf import load_schedule

BEIJING = timezone(timedelta(hours=8))


def main() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    # 只有网页上点 Run workflow 才强制跑；GitHub/Cloudflare 定时都走到点或补跑判断
    force = event == "workflow_dispatch"
    schedule = load_schedule()
    now = datetime.now(BEIJING)
    today = now.strftime("%Y-%m-%d")
    weekday_ok = now.isoweekday() == schedule.weekday
    on_hour = weekday_ok and now.hour == schedule.hour
    catch_up = weekday_ok and now.hour > schedule.hour and schedule.last_run != today
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
