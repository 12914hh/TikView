"""本地窗口：生成授权链接、更新播放量、设置自动更新时间。"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from dotenv import load_dotenv

from schedule_conf import WEEKDAYS, Schedule, load_schedule, validate, write_feishu
from state_sig import sign_state
from sync import ROOT
from tiktok import authorization_url


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TikView")
        self.geometry("680x540")
        load_dotenv(ROOT / ".env")
        self._saving_schedule = False
        self._schedule = Schedule()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="飞书作者 ID").pack(anchor="w")
        self.author = ttk.Entry(frame)
        self.author.pack(fill="x", pady=(4, 12))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="生成授权链接", command=self.make_link).pack(side="left")
        ttk.Button(buttons, text="复制链接", command=self.copy_link).pack(side="left", padx=8)
        ttk.Button(buttons, text="更新播放量", command=self.update_views).pack(side="left")

        schedule = ttk.LabelFrame(frame, text="自动更新（北京时间，开启后电脑关着也会跑）", padding=8)
        schedule.pack(fill="x", pady=(12, 0))
        row = ttk.Frame(schedule)
        row.pack(fill="x")
        ttk.Label(row, text="星期").pack(side="left")
        self.weekday = ttk.Combobox(row, values=WEEKDAYS, state="readonly", width=8)
        self.weekday.pack(side="left", padx=(6, 16))
        ttk.Label(row, text="小时").pack(side="left")
        self.hour = ttk.Combobox(
            row, values=[f"{item:02d}" for item in range(24)], state="readonly", width=4
        )
        self.hour.pack(side="left", padx=(6, 4))
        ttk.Label(row, text="点").pack(side="left")
        ttk.Button(row, text="保存时间", command=self.save_schedule).pack(side="left", padx=(16, 8))
        self.toggle_button = ttk.Button(row, text="开启定时任务", command=self.toggle_schedule)
        self.toggle_button.pack(side="left")
        self.schedule_hint = ttk.Label(schedule, text="正在读取当前时间…")
        self.schedule_hint.pack(anchor="w", pady=(8, 0))

        self.link = scrolledtext.ScrolledText(frame, height=4, wrap="word")
        self.link.pack(fill="x", pady=12)
        self.log = scrolledtext.ScrolledText(frame, height=12, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)
        self._apply_schedule(Schedule(source="默认"))
        self.after(200, self._refresh_schedule)

    def make_link(self) -> None:
        author_id = self.author.get().strip()
        secret = os.environ.get("STATE_SECRET", "").strip()
        client_key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
        redirect_uri = os.environ.get("TIKTOK_REDIRECT_URI", "").strip()
        if not author_id:
            messagebox.showwarning("TikView", "先填写飞书表里的作者 ID。")
            return
        if not secret or not client_key or not redirect_uri:
            messagebox.showerror("TikView", " .env 里还缺 STATE_SECRET、TIKTOK_CLIENT_KEY 或 TIKTOK_REDIRECT_URI。")
            return
        if "workers.dev" not in redirect_uri and not redirect_uri.rstrip("/").endswith("/callback"):
            self._write("当前回调还不是 Worker 地址。作者点完后不会自动保存，需要先部署回调并改 Redirect URI。\n")
        url = authorization_url(client_key, redirect_uri, sign_state(secret, author_id))
        self.link.delete("1.0", "end")
        self.link.insert("1.0", url)
        self.clipboard_clear()
        self.clipboard_append(url)
        self._write("授权链接已生成，并复制到剪贴板。发给这位作者即可。\n")

    def copy_link(self) -> None:
        text = self.link.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._write("链接已复制。\n")

    def save_schedule(self) -> None:
        schedule = self._schedule_from_widgets(self._schedule.enabled)
        if schedule is None:
            return
        self._persist_schedule(schedule, f"正在保存 {schedule.when()}…")

    def toggle_schedule(self) -> None:
        schedule = self._schedule_from_widgets(not self._schedule.enabled)
        if schedule is None:
            return
        action = "开启" if schedule.enabled else "停止"
        self._persist_schedule(schedule, f"正在{action}定时任务…")

    def _schedule_from_widgets(self, enabled: bool) -> Schedule | None:
        try:
            weekday = WEEKDAYS.index(self.weekday.get()) + 1
            hour = int(self.hour.get())
            validate(weekday, hour)
        except (ValueError, IndexError):
            messagebox.showwarning("TikView", "请选择星期和小时。")
            return None
        return Schedule(
            weekday=weekday,
            hour=hour,
            enabled=enabled,
            last_run=self._schedule.last_run,
        )

    def _persist_schedule(self, schedule: Schedule, message: str) -> None:
        if self._saving_schedule:
            self._write("上一次保存还在进行。\n")
            return
        self._saving_schedule = True
        self._write(message + "\n")
        threading.Thread(target=self._save_schedule, args=(schedule,), daemon=True).start()

    def _save_schedule(self, schedule: Schedule) -> None:
        error = ""
        try:
            write_feishu(schedule)
        except Exception as exc:
            error = str(exc)
        finally:
            self._saving_schedule = False
        self.after(0, lambda: self._after_save(schedule, error))

    def _after_save(self, schedule: Schedule, error: str) -> None:
        if error:
            self._write(f"飞书「配置」表写入失败：{error}\n")
            messagebox.showerror("TikView", "没有写上飞书「配置」表。看窗口里的说明。")
            return
        schedule.source = "飞书「配置」表"
        self._apply_schedule(schedule)
        if schedule.enabled:
            self._write(f"定时任务已开启，{schedule.when()} 会自动更新播放量，电脑可以关着。\n")
        else:
            self._write(f"已保存 {schedule.when()}。定时任务已停止，不会自动跑。点「开启定时任务」后才会跑。\n")

    def _refresh_schedule(self) -> None:
        threading.Thread(target=self._load_remote_schedule, daemon=True).start()

    def _load_remote_schedule(self) -> None:
        try:
            schedule = load_schedule()
        except Exception:
            return
        self.after(0, lambda: self._apply_schedule(schedule))

    def _apply_schedule(self, schedule: Schedule) -> None:
        self._schedule = schedule
        self.weekday.set(WEEKDAYS[schedule.weekday - 1])
        self.hour.set(f"{schedule.hour:02d}")
        self.toggle_button.configure(text="停止定时任务" if schedule.enabled else "开启定时任务")
        hint = f"当前：{schedule.when()}。定时任务{schedule.status()}"
        if schedule.source:
            hint += f"。来自{schedule.source}"
        if schedule.enabled:
            hint += "。到点会自动更新，电脑可以关着。"
        else:
            hint += "。点「开启定时任务」后才会自动跑。"
        self.schedule_hint.configure(text=hint)

    def update_views(self) -> None:
        if getattr(self, "_reader", None) is not None and self._reader.poll() is None:
            self._write("上一次更新还在进行。\n")
            return
        if getattr(self, "_updating", False):
            self._write("上一次更新还在进行。\n")
            return
        self._write("开始更新播放量…\n")
        if getattr(sys, "frozen", False):
            self._updating = True
            threading.Thread(target=self._run_pull, daemon=True).start()
            return
        python = _python()
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._reader = subprocess.Popen(
            [str(python), str(ROOT / "pull.py"), "--write"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            **kwargs,
        )
        self.after(100, self._read_output)

    def _run_pull(self) -> None:
        import io

        import pull

        buffer = io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        old_argv = sys.argv
        code = 1
        sys.stdout = buffer
        sys.stderr = buffer
        sys.argv = ["pull.py", "--write"]
        try:
            code = pull.main()
        except Exception as exc:
            buffer.write(f"{exc}\n")
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            sys.argv = old_argv
            self._updating = False
        text = buffer.getvalue() + f"结束，退出码 {code}\n"
        self.after(0, lambda: self._write(text))

    def _read_output(self) -> None:
        if self._reader.stdout is None:
            return
        line = self._reader.stdout.readline()
        if line:
            self._write(line)
        if self._reader.poll() is None:
            self.after(100, self._read_output)
            return
        rest = self._reader.stdout.read()
        if rest:
            self._write(rest)
        self._write(f"结束，退出码 {self._reader.returncode}\n")

    def _write(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")


def _python() -> Path:
    if sys.platform == "win32":
        candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = ROOT / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else Path(sys.executable)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
