"""Self-contained captcha / OTP solver implementations.

This module has zero dependencies on the ngdrs skill. It defines:

  1. `FileBasedSolver`     — default; writes a marker file + waits for a
                             value file. The screenshot is saved next to
                             the marker so the user (or an integrator)
                             can read it.

  2. `AIAnthropicSolver`   — uses Claude vision to read the captcha.
                             Imported lazily so the SDK is only required
                             when the AI is actually enabled.

  3. `CombinedSolver`      — tries the primary (AI) first, falls back to
                             a human (file-based) solver on failure. OTP
                             always uses the fallback (AI can't receive
                             an SMS).

  4. `create_solver(cfg)`  — factory; returns the right solver based on
                             a config dict.

The file-based protocol is the same as the ngdrs skill uses, so any
existing tooling that watches `awaiting_*.json` files will work unchanged.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Relative input paths (markers/values) resolve against the runner folder so
# cron jobs don't depend on the working directory.
_HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Solver protocol                                                             #
# --------------------------------------------------------------------------- #


class CaptchaSolver(ABC):
    """Pluggable captcha / OTP solver."""

    name: str = "abstract"

    @abstractmethod
    def solve_captcha(
        self,
        image_path: Path,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        """Return the captcha text shown in the image at `image_path`."""
        raise NotImplementedError

    @abstractmethod
    def get_otp(
        self,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        """Return the OTP the user just received by SMS."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Terminal (synchronous stdin) — for local debugging in head mode              #
# --------------------------------------------------------------------------- #


class TerminalSolver(CaptchaSolver):
    """Synchronous, terminal-based prompt. Perfect for head mode debugging.

    No file markers, no polling. Just `input(...)` in the same terminal
    where the runner is running. The captcha image path is printed so you
    can `open` it in a viewer, then type the answer.

    Trade-offs:
      ✓ Zero files, zero config, zero polling
      ✓ Best UX for local development
      ✗ Doesn't work in cron / Lambda / non-interactive contexts
    """

    name = "terminal"

    def __init__(self, *, image_open_cmd: Optional[str] = None) -> None:
        # `image_open_cmd` lets you override how the image is "shown".
        # Default: just print the path so the user can open it manually.
        self.image_open_cmd = image_open_cmd

    def _show_image(self, image_path: Path) -> None:
        path_str = str(image_path)
        sep = "=" * 64
        sys.stderr.write(f"\n{sep}\n")
        sys.stderr.write(f"  CAPTCHA IMAGE → {path_str}\n")
        sys.stderr.write(f"  (open this file in any image viewer to read it)\n")
        sys.stderr.write(f"{sep}\n")
        if self.image_open_cmd:
            import subprocess
            try:
                subprocess.Popen(
                    self.image_open_cmd.format(path=path_str),
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                sys.stderr.write(f"  (could not auto-open: {exc})\n")
        sys.stderr.flush()

    def _prompt(self, message: str) -> str:
        sys.stderr.write(f"\n{message}\n")
        sys.stderr.flush()
        # Flush stdout too in case something else is piped
        sys.stdout.flush()
        try:
            return input("> ").strip()
        except EOFError:
            raise RuntimeError("no stdin available — TerminalSolver needs an interactive TTY")

    # ---- public API ---- #

    def solve_captcha(
        self,
        image_path: Path,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        self._show_image(image_path)
        val = self._prompt(
            f"  Read the captcha image and type the characters below"
            + (f"  ({hint})" if hint else "")
        )
        if not val:
            raise RuntimeError("empty captcha — refusing to continue")
        sys.stderr.write(f"  [daily-runner] received captcha: {val!r}\n")
        return val

    def get_otp(
        self,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        val = self._prompt(
            "  Enter the OTP you just received by SMS"
            + (f"  ({hint})" if hint else "")
        )
        if not val:
            raise RuntimeError("empty OTP — refusing to continue")
        sys.stderr.write(f"  [daily-runner] received OTP (len={len(val)})\n")
        return val


# --------------------------------------------------------------------------- #
# File-based (default for cron / Lambda)                                      #
# --------------------------------------------------------------------------- #


class FileBasedSolver(CaptchaSolver):
    """File-based human-in-the-loop solver.

    Protocol (deterministic, restartable):
        1. Writes `<input_dir>/awaiting_<name>.json` with all context.
        2. Prints a clear instruction to stderr.
        3. Polls `<input_dir>/<name>.txt` every `poll_s` seconds.
        4. On success, returns the trimmed contents and deletes both
           files so re-runs don't reuse stale values.

    The captcha image is shared three ways:
        - path printed to stderr
        - `image_path` field in the marker JSON
        - base64 sidecar at `<image>.b64` for programmatic consumers
    """

    name = "file"

    def __init__(
        self,
        input_dir: Path,
        *,
        timeout_s: int = 300,
        poll_s: float = 1.0,
        share_base64: bool = True,
        otp_command: Optional[str] = None,
    ) -> None:
        self.input_dir = Path(input_dir)
        self.timeout_s = int(timeout_s)
        self.poll_s = float(poll_s)
        self.share_base64 = bool(share_base64)
        self.otp_command = otp_command
        self.input_dir.mkdir(parents=True, exist_ok=True)

    # ---- internal helpers ---- #

    def _marker_path(self, name: str) -> Path:
        return self.input_dir / f"awaiting_{name}.json"

    def _value_path(self, name: str) -> Path:
        return self.input_dir / f"{name}.txt"

    def _write_marker(
        self,
        name: str,
        *,
        hint: str,
        image_path: Optional[Path],
        run_id: Optional[str],
        deadline: datetime,
    ) -> Path:
        payload: dict[str, Any] = {
            "input": name,
            "hint": hint,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "deadline_at": deadline.isoformat(timespec="seconds"),
            "write_to": str(self._value_path(name)),
        }
        if image_path is not None:
            payload["image_path"] = str(image_path)
        if run_id:
            payload["run_id"] = run_id
        m = self._marker_path(name)
        m.write_text(json.dumps(payload, indent=2))
        return m

    def _announce(
        self,
        name: str,
        *,
        hint: str,
        image_path: Optional[Path],
        marker_path: Path,
        value_path: Path,
        deadline: datetime,
    ) -> None:
        sep = "=" * 64
        sys.stderr.write(f"\n{sep}\n")
        sys.stderr.write(f"[daily-runner] WAITING FOR {name!r}\n")
        sys.stderr.write(f"        marker:   {marker_path}\n")
        sys.stderr.write(f"        write to: {value_path}\n")
        if image_path is not None:
            sys.stderr.write(f"        image:    {image_path}\n")
            sys.stderr.write(
                f"        (open the file in any image viewer to read the captcha)\n"
            )
        sys.stderr.write(f"        hint:     {hint}\n")
        sys.stderr.write(
            f"        deadline: {deadline.isoformat(timespec='seconds')}\n"
        )
        sys.stderr.write(f"{sep}\n\n")
        sys.stderr.flush()

    def _share_image(self, image_path: Path) -> Optional[Path]:
        if not self.share_base64 or image_path is None or not image_path.exists():
            return None
        try:
            b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        except Exception as exc:
            sys.stderr.write(f"[daily-runner] could not base64 encode image: {exc!r}\n")
            return None
        b64_path = image_path.with_suffix(image_path.suffix + ".b64")
        b64_path.write_text(b64)
        sys.stderr.write(
            f"        base64:   data:image/png;base64,{b64[:80]}… "
            f"(full: {b64_path})\n"
        )
        return b64_path

    def _await(
        self,
        name: str,
        *,
        hint: str,
        image_path: Optional[Path],
        run_id: Optional[str],
    ) -> str:
        deadline_dt = datetime.now() + timedelta(seconds=self.timeout_s)
        marker = self._write_marker(
            name,
            hint=hint,
            image_path=image_path,
            run_id=run_id,
            deadline=deadline_dt,
        )
        value = self._value_path(name)
        self._announce(
            name,
            hint=hint,
            image_path=image_path,
            marker_path=marker,
            value_path=value,
            deadline=deadline_dt,
        )
        if image_path:
            self._share_image(image_path)

        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if value.exists():
                content = value.read_text().strip()
                if content:
                    value.unlink()
                    if marker.exists():
                        marker.unlink()
                    sys.stderr.write(
                        f"[daily-runner] received {name!r}: {content!r}\n"
                    )
                    return content
            time.sleep(self.poll_s)

        if marker.exists():
            marker.unlink()
        raise TimeoutError(
            f"Timed out waiting for {name!r} after {self.timeout_s}s "
            f"(expected at {value})"
        )

    # ---- public API ---- #

    def solve_captcha(
        self,
        image_path: Path,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        return self._await(
            "captcha",
            hint=hint or "Read the captcha image and write the characters",
            image_path=image_path,
            run_id=run_id,
        )

    def get_otp(
        self,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        # Cron hook: if an OTP command is configured (SMS forwarder, IMAP
        # poller, Android bridge…), run it first. Its first stdout line is
        # used verbatim; an empty output or non-zero exit falls back to the
        # file/inbox protocol below.
        if self.otp_command:
            import subprocess

            sys.stderr.write(
                f"[daily-runner] running otp_command: {self.otp_command!r}\n"
            )
            try:
                proc = subprocess.run(
                    self.otp_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=min(self.timeout_s, 120),
                )
                otp = (proc.stdout or "").strip().splitlines()
                if proc.returncode == 0 and otp and otp[0].strip():
                    sys.stderr.write("[daily-runner] otp_command returned a value\n")
                    return otp[0].strip()
                sys.stderr.write(
                    f"[daily-runner] otp_command gave no value "
                    f"(rc={proc.returncode}); falling back to file input\n"
                )
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(
                    f"[daily-runner] otp_command failed ({exc!r}); "
                    f"falling back to file input\n"
                )

        return self._await(
            "otp",
            hint=hint or "Enter the OTP received on your registered mobile",
            image_path=None,
            run_id=run_id,
        )


# --------------------------------------------------------------------------- #
# AI vision solver (Anthropic Claude)                                         #
# --------------------------------------------------------------------------- #


class AIAnthropicSolver(CaptchaSolver):
    """Reads captcha images using Anthropic Claude vision.

    The `anthropic` SDK is imported lazily: it is only required when this
    class is actually constructed. If the SDK is missing, instantiation
    raises a clear error rather than failing at module import.

    NOTE: AI cannot receive an SMS, so `get_otp` always raises and the
    `CombinedSolver` falls back to the human solver for OTP.
    """

    name = "ai-anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 64,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed. Run: pip install anthropic"
            ) from exc
        if not api_key:
            raise ValueError("AIAnthropicSolver requires a non-empty api_key")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = int(max_tokens)

    def _detect_media_type(self, image_path: Path) -> str:
        suffix = image_path.suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "image/png")

    def _read_image_b64(self, image_path: Path) -> str:
        return base64.b64encode(image_path.read_bytes()).decode("ascii")

    def solve_captcha(
        self,
        image_path: Path,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        if not image_path or not image_path.exists():
            raise FileNotFoundError(f"captcha image not found: {image_path}")
        media_type = self._detect_media_type(image_path)
        b64 = self._read_image_b64(image_path)

        prompt = (
            "This is a CAPTCHA image from the Delhi NGDRS e-Search portal. "
            "Read the alphanumeric characters shown in the image and respond "
            "with ONLY those characters in the correct case — no explanation, "
            "no punctuation, no surrounding quotes, no whitespace. "
            "If the image is unreadable or you are uncertain, respond with "
            "the single word UNREADABLE."
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()
        if not text or text.upper() == "UNREADABLE":
            raise RuntimeError(f"AI could not read captcha (response: {text!r})")
        sys.stderr.write(f"[daily-runner] AI solved captcha: {text!r}\n")
        return text

    def get_otp(
        self,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        raise NotImplementedError(
            "AI cannot receive SMS; AIAnthropicSolver does not implement get_otp"
        )


# --------------------------------------------------------------------------- #
# Combined (AI first, human fallback)                                         #
# --------------------------------------------------------------------------- #


class CombinedSolver(CaptchaSolver):
    """Tries the primary (AI) solver first; on any failure falls back to
    the secondary (human) solver. OTP always uses the secondary because
    the AI cannot receive an SMS.
    """

    name = "combined"

    def __init__(self, primary: CaptchaSolver, fallback: CaptchaSolver) -> None:
        self.primary = primary
        self.fallback = fallback

    def solve_captcha(
        self,
        image_path: Path,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        try:
            return self.primary.solve_captcha(
                image_path, hint=hint, run_id=run_id
            )
        except Exception as exc:
            sys.stderr.write(
                f"[daily-runner] primary solver {self.primary.name!r} failed: {exc!r}\n"
                f"[daily-runner] falling back to {self.fallback.name!r}\n"
            )
            return self.fallback.solve_captcha(
                image_path, hint=hint, run_id=run_id
            )

    def get_otp(
        self,
        *,
        hint: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        return self.fallback.get_otp(hint=hint, run_id=run_id)


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #


def create_solver(config: dict[str, Any]) -> CaptchaSolver:
    """Build a solver from a config dict.

    Solver selection (first match wins):
      1. `verification.solver = "terminal"`  → TerminalSolver (sync stdin)
      2. `verification.solver = "file"`      → FileBasedSolver (default)
      3. `ai.enabled && ai.api_key`          → CombinedSolver(AI, FileBased)
      4. else                                → FileBasedSolver

    The config dict is the same shape as `config.json`:

        {
          "verification": {"solver": "terminal" | "file"},
          "ai": {
            "enabled": bool,
            "provider": "anthropic",
            "api_key": "sk-ant-...",
            "model": "claude-sonnet-4-5",
            "fallback_on_failure": true
          },
          "paths": {"input_dir": "data/state/inputs"},
          ...
        }
    """
    paths = config.get("paths", {}) or {}
    verif = config.get("verification", {}) or {}
    ai_cfg = config.get("ai", {}) or {}

    solver_kind = (verif.get("solver") or "file").lower()
    input_dir = Path(paths.get("input_dir", "data/state/inputs"))
    if not input_dir.is_absolute():
        input_dir = (_HERE / input_dir).resolve()
    timeout_s = int(verif.get("input_timeout_seconds", 300))
    poll_s = float(verif.get("poll_interval_seconds", 1.0))
    share_b64 = bool(verif.get("share_screenshot_base64", True))
    image_open_cmd = verif.get("image_open_cmd")
    otp_command = verif.get("otp_command")

    # ---- terminal solver (for local head-mode debugging) ---- #
    if solver_kind == "terminal":
        sys.stderr.write(
            "[daily-runner] using TerminalSolver — captcha + OTP will be "
            "asked in THIS terminal. Don't pipe stdin or this won't work.\n"
        )
        return TerminalSolver(image_open_cmd=image_open_cmd)

    # ---- file solver (for cron / Lambda) ---- #
    file_solver = FileBasedSolver(
        input_dir,
        timeout_s=timeout_s,
        poll_s=poll_s,
        share_base64=share_b64,
        otp_command=otp_command,
    )

    # ---- AI (only meaningful with the file solver) ---- #
    if solver_kind not in ("file", "auto"):
        sys.stderr.write(
            f"[daily-runner] unknown solver {solver_kind!r}; "
            f"falling back to file-based\n"
        )

    if ai_cfg.get("enabled") and ai_cfg.get("api_key"):
        provider = (ai_cfg.get("provider") or "anthropic").lower()
        if provider != "anthropic":
            raise ValueError(
                f"unsupported AI provider {provider!r}; only 'anthropic' is wired up"
            )
        ai = AIAnthropicSolver(
            api_key=ai_cfg["api_key"],
            model=ai_cfg.get("model", "claude-sonnet-4-5"),
            max_tokens=int(ai_cfg.get("max_tokens", 64)),
        )
        sys.stderr.write(
            f"[daily-runner] AI captcha solver enabled "
            f"(provider={provider}, model={ai.model}); "
            f"OTP always falls back to human\n"
        )
        return CombinedSolver(ai, file_solver)

    sys.stderr.write(
        "[daily-runner] AI captcha solver disabled — using human (file-based) "
        "solver for both captcha and OTP\n"
    )
    return file_solver


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _cli() -> int:
    """Standalone CLI: wait for a captcha or OTP. Useful for debugging."""
    p = argparse.ArgumentParser(description="Wait for a captcha or OTP value file.")
    p.add_argument("--input-dir", default="data/state/inputs")
    p.add_argument("--wait", choices=["captcha", "otp"], required=True)
    p.add_argument("--image", help="captcha image path (required when --wait=captcha)")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--poll", type=float, default=1.0)
    p.add_argument("--no-base64", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    solver = FileBasedSolver(
        Path(args.input_dir),
        timeout_s=args.timeout,
        poll_s=args.poll,
        share_base64=not args.no_base64,
    )
    if args.wait == "captcha":
        if not args.image:
            print("--image is required when --wait=captcha", file=sys.stderr)
            return 2
        val = solver.solve_captcha(Path(args.image), run_id=args.run_id)
    else:
        val = solver.get_otp(run_id=args.run_id)
    print(val)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
