#!/usr/bin/env python3
"""Open BJMU HPC SSH/SFTP sessions without aliases or exposed secrets."""

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import pty
import re
import select
import shlex
import shutil
import signal
import struct
import sys
import termios
import time
from dataclasses import dataclass


OTP_PATTERN = re.compile(r"^\d{6}$")
ANSI_PATTERN = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
SAFE_USER = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_HOST = re.compile(r"^[A-Za-z0-9.:-]+$")
SAFE_NODE_PREFIX = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_BASTION = "10.100.0.88"
DEFAULT_SFTP_TARGET = "10.100.0.5"
DEFAULT_OTP_ENTRY = "otp/aidd"
AUTH_PROMPT = re.compile(
    r"(?:password|verification(?:\s+code)?|one[- ]time|otp|token|passcode|"
    r"dynamic\s+code|动态(?:口令|密钥|令牌)|验证码|二次验证)[^\r\n]{0,96}[:：]\s*$",
    re.IGNORECASE,
)
ASSET_PROMPT = re.compile(
    r"(?:\bopt\s*>|\[host\]\s*>|(?:select|choose|input).{0,48}(?:asset|host)|"
    r"请选择.{0,32}(?:资产|主机)|输入.{0,32}(?:资产|主机))[^\r\n]*$",
    re.IGNORECASE,
)


class ConnectError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    user: str
    bastion: str
    sftp_target: str
    otp_entry: str
    node_prefix: str
    default_node: int
    otp_timeout: float

    @property
    def sftp_route(self) -> str:
        return f"{self.user}/{self.sftp_target}/{self.user}@{self.bastion}"


def _positive_float(name: str, default: str) -> float:
    raw = os.environ.get(name, default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConnectError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ConnectError(f"{name} must be a positive number")
    return value


def load_config() -> Config:
    user = os.environ.get("BHC_USER", "").strip()
    bastion = os.environ.get("BHC_BASTION", DEFAULT_BASTION).strip()
    sftp_target = os.environ.get("BHC_SFTP_TARGET", DEFAULT_SFTP_TARGET).strip()
    otp_entry = os.environ.get("BHC_OTP_ENTRY", DEFAULT_OTP_ENTRY).strip()
    node_prefix = os.environ.get("BHC_NODE_PREFIX", "login").strip()
    try:
        default_node = int(os.environ.get("BHC_DEFAULT_NODE", "5"))
    except ValueError as exc:
        raise ConnectError("BHC_DEFAULT_NODE must be an integer from 1 to 7") from exc

    if not user or not SAFE_USER.fullmatch(user):
        raise ConnectError("BHC_USER is required and may contain only letters, digits, '.', '_', or '-'")
    if not SAFE_HOST.fullmatch(bastion):
        raise ConnectError("BHC_BASTION contains unsupported characters")
    if not SAFE_HOST.fullmatch(sftp_target):
        raise ConnectError("BHC_SFTP_TARGET contains unsupported characters")
    if not otp_entry:
        raise ConnectError("BHC_OTP_ENTRY must not be empty")
    if not SAFE_NODE_PREFIX.fullmatch(node_prefix):
        raise ConnectError("BHC_NODE_PREFIX contains unsupported characters")
    if default_node not in range(1, 8):
        raise ConnectError("BHC_DEFAULT_NODE must be an integer from 1 to 7")

    return Config(
        user=user,
        bastion=bastion,
        sftp_target=sftp_target,
        otp_entry=otp_entry,
        node_prefix=node_prefix,
        default_node=default_node,
        otp_timeout=_positive_float("BHC_OTP_TIMEOUT", "20"),
    )


def bootstrap_interactive_environment() -> None:
    """Reload interactive Bash once so exported local credentials are available."""
    marker = "BJMU_CONNECT_BOOTSTRAPPED"
    if os.environ.get("DEFAULT_PWD") or os.environ.get(marker) == "1":
        return
    command = shlex.join([sys.executable, os.path.abspath(__file__), *sys.argv[1:]])
    os.execvp("bash", ["bash", "-ic", f"export {marker}=1; exec {command}"])


def read_otp(timeout: float, otp_entry: str) -> str:
    if shutil.which("gopass") is None:
        raise ConnectError("gopass is not installed or is not on PATH")

    secret_read_fd, secret_write_fd = os.pipe()
    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        os.close(secret_read_fd)
        os.dup2(secret_write_fd, sys.stdout.fileno())
        if secret_write_fd != sys.stdout.fileno():
            os.close(secret_write_fd)
        os.execvp("gopass", ["gopass", "otp", "-o", otp_entry])

    os.close(secret_write_fd)
    prompt_output = bytearray()
    secret_output = bytearray()
    passphrase_sent = False
    deadline = time.monotonic() + timeout
    status: int | None = None
    try:
        while time.monotonic() < deadline:
            wait_time = max(0.0, min(0.25, deadline - time.monotonic()))
            readable, _, _ = select.select([master_fd, secret_read_fd], [], [], wait_time)
            if master_fd in readable:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    chunk = b""
                if chunk:
                    prompt_output.extend(chunk)
                    prompt_text = normalize(bytes(prompt_output[-8192:]))
                    if not passphrase_sent and "Passphrase:" in prompt_text:
                        passphrase = os.environ.get("BHC_GPG_PASSPHRASE") or os.environ.get("DEFAULT_PWD")
                        if not passphrase:
                            raise ConnectError(
                                "BHC_GPG_PASSPHRASE is unset and DEFAULT_PWD is unavailable to unlock gopass"
                            )
                        os.write(master_fd, passphrase.encode("utf-8") + b"\r")
                        passphrase_sent = True
            if secret_read_fd in readable:
                chunk = os.read(secret_read_fd, 4096)
                if chunk:
                    secret_output.extend(chunk)
            waited_pid, waited_status = os.waitpid(child_pid, os.WNOHANG)
            if waited_pid == child_pid:
                status = waited_status
                break
        if status is None:
            os.kill(child_pid, signal.SIGTERM)
            os.waitpid(child_pid, 0)
            raise ConnectError(f"gopass timed out while reading {otp_entry}")
    except BaseException:
        try:
            waited_pid, _ = os.waitpid(child_pid, os.WNOHANG)
            if waited_pid == 0:
                os.kill(child_pid, signal.SIGTERM)
                os.waitpid(child_pid, 0)
        except (ChildProcessError, ProcessLookupError):
            pass
        raise
    finally:
        os.close(master_fd)
        try:
            while True:
                chunk = os.read(secret_read_fd, 4096)
                if not chunk:
                    break
                secret_output.extend(chunk)
        finally:
            os.close(secret_read_fd)

    if os.waitstatus_to_exitcode(status) != 0:
        raise ConnectError(f"gopass could not read {otp_entry}")
    plain_output = secret_output.decode("utf-8", errors="ignore")
    candidates = [line.strip() for line in plain_output.splitlines() if OTP_PATTERN.fullmatch(line.strip())]
    if len(candidates) != 1:
        raise ConnectError("gopass returned no unambiguous six-digit OTP")
    return candidates[0]


def terminal_size(fd: int) -> bytes:
    try:
        return fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
    except OSError:
        return struct.pack("HHHH", 24, 80, 0, 0)


def set_terminal_size(fd: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, terminal_size(sys.stdin.fileno()))
    except OSError:
        pass


def normalize(data: bytes) -> str:
    return ANSI_PATTERN.sub(b"", data).decode("utf-8", errors="ignore").replace("\r", "")


@dataclass
class Automation:
    mode: str
    otp: str
    node: str
    auth_sent: bool = False
    node_sent: bool = False
    buffer: str = ""

    def feed(self, data: bytes, fd: int) -> None:
        self.buffer = (self.buffer + normalize(data))[-32768:]
        tail = self.buffer[-2048:]
        if not self.auth_sent and AUTH_PROMPT.search(tail):
            credential = self.otp
            if self.mode == "sftp":
                password = os.environ.get("DEFAULT_PWD")
                if not password:
                    raise ConnectError("DEFAULT_PWD is unset; it is required for SFTP authentication")
                credential = f"{password} {self.otp}"
            os.write(fd, credential.encode("utf-8") + b"\n")
            self.auth_sent = True
            self.buffer = ""
            return
        if self.mode == "ssh" and self.auth_sent and not self.node_sent and ASSET_PROMPT.search(tail):
            os.write(fd, self.node.encode("utf-8") + b"\n")
            self.node_sent = True
            self.buffer = ""


def bridge(mode: str, node: str, otp_timeout: float, config: Config) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ConnectError("an interactive TTY is required")

    required = ("sshpass", "ssh") if mode == "ssh" else ("sftp",)
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        raise ConnectError("missing executable(s): " + ", ".join(missing))
    password = os.environ.get("DEFAULT_PWD")
    if mode == "ssh" and not password:
        raise ConnectError("DEFAULT_PWD is unset; it is required for SSH first-factor authentication")
    if mode == "sftp" and not password:
        raise ConnectError("DEFAULT_PWD is unset; it is required for SFTP authentication")

    otp = read_otp(otp_timeout, config.otp_entry)
    automation = Automation(mode=mode, otp=otp, node=node)
    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        child_env = os.environ.copy()
        child_env.pop("DEFAULT_PWD", None)
        child_env.pop("BHC_GPG_PASSPHRASE", None)
        child_env.pop("SSHPASS", None)
        if mode == "ssh":
            password_read_fd, password_write_fd = os.pipe()
            os.write(password_write_fd, password.encode("utf-8"))
            os.close(password_write_fd)
            os.set_inheritable(password_read_fd, True)
            command = [
                "sshpass",
                "-d",
                str(password_read_fd),
                "ssh",
                f"{config.user}@{config.bastion}",
            ]
        else:
            command = ["sftp", config.sftp_route]
        os.execvpe(command[0], command, child_env)

    original = termios.tcgetattr(sys.stdin.fileno())
    set_terminal_size(master_fd)

    def resize(_signum: int, _frame: object) -> None:
        set_terminal_size(master_fd)

    old_winch = signal.signal(signal.SIGWINCH, resize)
    try:
        tty_state = termios.tcgetattr(sys.stdin.fileno())
        tty_state[3] &= ~(termios.ICANON | termios.ECHO)
        tty_state[6][termios.VMIN] = 1
        tty_state[6][termios.VTIME] = 0
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, tty_state)

        while True:
            readable, _, _ = select.select([master_fd, sys.stdin.fileno()], [], [])
            if master_fd in readable:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                os.write(sys.stdout.fileno(), chunk)
                automation.feed(chunk, master_fd)
            if sys.stdin.fileno() in readable:
                user_data = os.read(sys.stdin.fileno(), 65536)
                if not user_data:
                    break
                os.write(master_fd, user_data)
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original)
        signal.signal(signal.SIGWINCH, old_winch)
        os.close(master_fd)

    _, status = os.waitpid(child_pid, 0)
    return os.waitstatus_to_exitcode(status)


def check(otp_timeout: float, include_otp: bool, config: Config) -> int:
    missing = [name for name in ("ssh", "sshpass", "sftp", "gopass") if shutil.which(name) is None]
    if missing:
        raise ConnectError("missing executable(s): " + ", ".join(missing))
    if not os.environ.get("DEFAULT_PWD"):
        raise ConnectError("DEFAULT_PWD is unset")
    if include_otp:
        read_otp(otp_timeout, config.otp_entry)
    print("BJMU HPC connector prerequisites are ready; no secret values were displayed.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open BJMU HPC SSH/SFTP sessions with in-memory OTP injection.",
    )
    parser.add_argument(
        "--otp-timeout",
        type=float,
        default=None,
        help="seconds allowed for gopass; defaults to BHC_OTP_TIMEOUT or 20",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    ssh_parser = subparsers.add_parser("ssh", help="connect to a numbered cluster login node")
    ssh_parser.add_argument(
        "-N",
        "--node",
        type=int,
        choices=range(1, 8),
        default=None,
        metavar="{1..7}",
        help="login node number; defaults to BHC_DEFAULT_NODE or 5",
    )

    subparsers.add_parser("sftp", help="open the routed cluster SFTP session")

    check_parser = subparsers.add_parser("check", help="validate local prerequisites")
    check_parser.add_argument("--with-otp", action="store_true", help="also validate OTP retrieval")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        bootstrap_interactive_environment()
        config = load_config()
        otp_timeout = args.otp_timeout if args.otp_timeout is not None else config.otp_timeout
        if otp_timeout <= 0:
            raise ConnectError("--otp-timeout must be a positive number")
        if args.mode == "check":
            return check(otp_timeout, args.with_otp, config)
        if args.mode == "ssh":
            node_number = args.node if args.node is not None else config.default_node
            node_name = f"{config.node_prefix}{node_number:02d}"
            return bridge("ssh", node_name, otp_timeout, config)
        return bridge("sftp", "", otp_timeout, config)
    except (ConnectError, OSError) as exc:
        print(f"bhc: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
