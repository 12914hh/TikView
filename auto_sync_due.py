"""GitHub 定时任务用。开关打开，并且到了设定的北京时间，才继续跑。"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

from schedule_conf import load_schedule

BEIJING = timezone(timedelta(hours=8))


def main() -> int:
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    schedule = load_schedule()
    now = datetime.now(BEIJING)
    time_ok = now.isoweekday() == schedule.weekday and now.hour == schedule.hour
    due = schedule.enabled and (manual or time_ok)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"due={'true' if due else 'false'}\n")
    if not schedule.enabled:
        result = "定时任务已停止，本次跳过。"
    elif due:
        result = "本次执行。"
    else:
        result = "本次跳过。"
    print(
        f"北京时间 {now:%Y-%m-%d %H:%M}，{schedule.when()}，"
        f"{schedule.status()}，来源 {schedule.source}，{result}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
