import re
import shlex
import subprocess
import time
import uuid


class TmuxPane:
    def __init__(self):
        self.name = f"pipython-e2e-{uuid.uuid4().hex[:8]}"

    def start(self, cmd: str, env: dict[str, str], cwd: str) -> None:
        """cwd 必须是项目根——`uv run` 在无 pyproject 的目录找不到 pipython
        （审核实测必现失败）；agent 的目标目录用 `pipython --cwd` 传递。"""
        env_prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                self.name,
                "-x",
                "100",
                "-y",
                "30",
                "-c",
                cwd,
                f"{env_prefix} {cmd}",
            ],
            check=True,
        )
        # 会话是 detached 创建、从未被 client attach 过；tmux 默认行为是
        # "唯一窗口的唯一 pane 的进程退出 → 立即销毁 pane/window/session"，
        # 这会在 poll 到达前就把 scrollback 连同 session 一起清空（实测：
        # Ctrl+D 后 has-session 立即返回非 0，capture-pane 拿到空字符串）。
        # remain-on-exit 让 pane 在进程退出后原地保留（显示 "Pane is dead"
        # 但滚动区内容不变），使 wait_for 仍能 poll 到退出前打印的最后一行。
        subprocess.run(
            ["tmux", "set-option", "-t", self.name, "remain-on-exit", "on"],
            check=True,
        )

    def send(self, text: str) -> None:
        subprocess.run(["tmux", "send-keys", "-t", self.name, text, "Enter"], check=True)

    def send_ctrl_c(self) -> None:
        subprocess.run(["tmux", "send-keys", "-t", self.name, "C-c"], check=True)

    def send_ctrl_d(self) -> None:
        subprocess.run(["tmux", "send-keys", "-t", self.name, "C-d"], check=True)

    def capture(self) -> str:
        # -J：把终端原生软换行（填满列宽后自动折行，如长 session 路径）重新拼
        # 回逻辑单行，否则长行会在任意列边界被截断，patterns 匹配不到。
        out = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", self.name], capture_output=True, text=True
        )
        return out.stdout

    def wait_for(self, pattern: str, timeout: float = 10.0) -> str:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            last = self.capture()
            if re.search(pattern, last):
                return last
            time.sleep(0.2)
        raise AssertionError(
            f"pattern {pattern!r} not seen within {timeout}s; last screen:\n{last}"
        )

    def wait_dead(self, timeout: float = 10.0) -> str:
        # exit 断言不能只信 "session: " 这行文字——挂起在横幅后的进程也会打印过
        # 这行再卡死。remain-on-exit 让 tmux 在被驱动进程退出后于 pane 内追加一行
        # "Pane is dead ..."；poll 到这行才代表进程真正 exit，而不是恰好卡在同一屏。
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            last = self.capture()
            if "Pane is dead" in last:
                return last
            time.sleep(0.2)
        raise AssertionError(f"pane not dead within {timeout}s; last screen:\n{last}")

    def alive(self) -> bool:
        return (
            subprocess.run(["tmux", "has-session", "-t", self.name], capture_output=True).returncode
            == 0
        )

    def _graceful_stop(self, timeout: float = 3.0) -> None:
        # tmux kill-session 只 SIGHUP pane 里的顶层进程；app 的 bash 工具用
        # start_new_session=True 起了独立进程组，SIGHUP 到不了那个组，测试失败在
        # 中断场景里会留下孤儿 `sleep 30`。先发 C-c：这条到达 app 本身，触发
        # CancelledError，app 自己的 killpg 清理它派生的子进程；poll 到 pane 死亡
        # 或 session 消失即成功，再由调用方兜底 kill-session。
        subprocess.run(["tmux", "send-keys", "-t", self.name, "C-c"], capture_output=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.alive() or "Pane is dead" in self.capture():
                return
            time.sleep(0.2)

    def kill(self) -> None:
        # 优雅路径是尽力而为：无论它成功、超时还是抛异常，都不能掩盖测试本身的
        # 失败，也必须继续兜底执行 kill-session（否则失败路径上 session 和其
        # 子进程组都可能残留）。
        try:
            self._graceful_stop()
        except Exception:
            pass
        finally:
            subprocess.run(["tmux", "kill-session", "-t", self.name], capture_output=True)
