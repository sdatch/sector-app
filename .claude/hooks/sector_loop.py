#!/usr/bin/env python
"""Change-triggered test/verify loop for sector-app.

Two hooks drive it (see .claude/settings.json and sector-app-test-deploy.md):

  stamp  PostToolUse on Write|Edit — classifies the edited file and records
         which verification stages it invalidated. Silent, ~10 ms.
  gate   Stop — runs the deterministic stages (pytest, next build) itself,
         and blocks the turn with instructions for the stages that need an
         agent (compose rebuild + health, browser click-through, git push).

State lives in .claude/.loop-state.json. Stages are cleared as they pass, so
the loop converges: it keeps blocking until every stage a change touched is
green, up to MAX_ATTEMPTS blocks per change set.

Set SECTOR_LOOP=off to disable both hooks without editing settings.
SECTOR_LOOP_PUSH=auto lets the push stage run without asking; anything else
(the default) means Claude confirms before pushing. SECTOR_LOOP_GIT_REMOTE
names the remote to push to when it is not `origin`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
STATE_PATH = ROOT / ".claude" / ".loop-state.json"

# Stage order is the order they run in.
STAGES = ("pytest", "build", "stack", "ui", "push")
AGENT_STAGES = ("stack", "ui", "push")  # run by Claude, not by this script
# `push` is held back until everything before it is green — nothing leaves this
# machine on the strength of a half-finished verification.
LOCAL_STAGES = ("pytest", "build", "stack", "ui")
MAX_ATTEMPTS = 5

# Never re-verify because of an edit to these.
IGNORED_TOP = {".claude", "docs", "data"}
IGNORED_PARTS = {"node_modules", ".next", ".venv", "__pycache__", ".git", "artifacts"}

# Where the push stage sends the work. Overridable per-checkout by pointing the
# `origin` remote (or SECTOR_LOOP_GIT_REMOTE) somewhere else; this is only the
# value quoted in setup instructions.
REMOTE_URL = "https://github.com/sdatch/sector-app"

PYTEST_TIMEOUT = 420
BUILD_TIMEOUT = 420
TAIL_LINES = 25


# --------------------------------------------------------------------------- state


def load_state() -> dict:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state.setdefault("pending", [])
    state.setdefault("files", [])
    state.setdefault("attempts", 0)
    state.setdefault("signature", "")
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def ordered(stages) -> list[str]:
    return [s for s in STAGES if s in set(stages)]


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def read_input() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def disabled() -> bool:
    return os.environ.get("SECTOR_LOOP", "").lower() in {"off", "0", "false"}


# ----------------------------------------------------------------------- classify


def classify(rel: Path) -> set[str]:
    """Which verification stages does a change to this path invalidate?

    Anything worth verifying is also worth pushing, so every non-empty result
    picks up `push`.
    """
    stages = classify_verification(rel)
    return stages | {"push"} if stages else stages


def classify_verification(rel: Path) -> set[str]:
    parts = rel.parts
    if not parts:
        return set()
    if parts[0] in IGNORED_TOP or IGNORED_PARTS & set(parts):
        return set()

    name, suffix = rel.name, rel.suffix.lower()
    posix = rel.as_posix()

    # Infra: anything that changes how the containers are built or started.
    if name in {"docker-compose.yml", "docker-compose.yaml"} or name.startswith("Dockerfile"):
        return {"stack", "ui"}
    if posix == "backend/requirements.txt":
        return {"pytest", "stack"}
    if posix in {"frontend/package.json", "frontend/package-lock.json"}:
        return {"build", "stack", "ui"}

    if parts[0] == "backend":
        if suffix != ".py" and suffix not in {".ini", ".toml", ".cfg"}:
            return set()
        stages = {"pytest", "stack"}
        # A change to the wire surface deserves a real click-through.
        if posix.startswith(("backend/app/api/", "backend/app/contracts/")):
            stages.add("ui")
        return stages

    if parts[0] == "frontend":
        if suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".json"}:
            return set()
        return {"build", "stack", "ui"}

    return set()


# ---------------------------------------------------------------------- run stages


def backend_python() -> Path | None:
    for candidate in (
        ROOT / "backend" / ".venv" / "Scripts" / "python.exe",
        ROOT / "backend" / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return candidate
    return None


def tail(text: str, lines: int = TAIL_LINES) -> str:
    kept = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    return "\n".join(kept[-lines:])


def run(cmd, cwd: Path, timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            timeout=timeout,
            capture_output=True,
            text=True,
            shell=isinstance(cmd, str),
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as exc:
        return False, f"could not start: {exc}"
    output = tail((proc.stdout or "") + "\n" + (proc.stderr or ""))
    return proc.returncode == 0, output


def stage_pytest() -> tuple[bool, str]:
    python = backend_python()
    if python is None:
        return False, "backend/.venv not found — create it (see CLAUDE.md 'Running')"
    return run(
        [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        ROOT / "backend",
        PYTEST_TIMEOUT,
    )


def stage_build() -> tuple[bool, str]:
    if not (ROOT / "frontend" / "node_modules").exists():
        return False, "frontend/node_modules missing — run `npm install` in frontend/"
    return run("npm run build", ROOT / "frontend", BUILD_TIMEOUT)


RUNNERS = {"pytest": stage_pytest, "build": stage_build}


# ------------------------------------------------------------------------- git


def git(*args: str) -> tuple[bool, str]:
    """git, with stderr kept out of the value — a fatal must not become a branch name."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(ROOT), timeout=30, capture_output=True, text=True
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return proc.returncode == 0, (proc.stdout or "").strip()


def git_state() -> dict:
    """What the push stage needs to know, or why it cannot run."""
    remote = os.environ.get("SECTOR_LOOP_GIT_REMOTE", "origin")
    if not (ROOT / ".git").exists():
        return {
            "ready": False,
            "why": f"not a git repository yet — `git init && git remote add {remote} {REMOTE_URL}`",
        }
    ok, url = git("remote", "get-url", remote)
    if not ok or not url:
        return {"ready": False, "why": f"no `{remote}` remote — `git remote add {remote} {REMOTE_URL}`"}
    ok, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not ok or not branch:
        # A repo with no commits yet has no resolvable HEAD, but it has a ref.
        _, branch = git("symbolic-ref", "--short", "HEAD")
    _, dirty = git("status", "--porcelain")
    return {
        "ready": True,
        "remote": remote,
        "url": url.splitlines()[-1],
        "branch": (branch.splitlines() or ["HEAD"])[0] or "HEAD",
        "dirty": bool(dirty),
    }


# --------------------------------------------------------------------- hook: stamp


def cmd_stamp() -> int:
    if disabled():
        return 0
    data = read_input()
    tool_input = data.get("tool_input") or {}
    raw = (
        tool_input.get("file_path")
        or (data.get("tool_response") or {}).get("filePath")
        or ""
    )
    if not raw:
        return 0
    try:
        rel = Path(raw).resolve().relative_to(ROOT.resolve())
    except (ValueError, OSError):
        return 0

    stages = classify(rel)
    if not stages:
        return 0

    state = load_state()
    before = set(state["pending"])
    state["pending"] = ordered(before | stages)
    files = [f for f in state["files"] if f != rel.as_posix()]
    state["files"] = (files + [rel.as_posix()])[-40:]
    if set(state["pending"]) != before:
        # New ground to cover — the loop gets a fresh budget of attempts.
        state["attempts"] = 0
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    return 0


# ---------------------------------------------------------------------- hook: gate


def instructions(state: dict, pending: list[str], results: list[str]) -> str:
    files = state.get("files") or []
    lines = ["sector-app verify loop — changes since the last green run:"]
    lines.append("  " + ", ".join(files[-12:]) if files else "  (unknown)")
    if results:
        lines.append("")
        lines.extend(results)
    lines.append("")
    lines.append("Still to do (run these, then continue):")

    asked = []
    if "stack" in pending:
        asked.append("stack")
        lines.append(
            "  3. Rebuild the stack: `docker compose up --build -d`, then health-check\n"
            "     `curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health` (expect 200)\n"
            "     and `curl -s -o /dev/null -w '%{http_code}' http://localhost:3000` (expect 200)."
        )
    if "ui" in pending:
        asked.append("ui")
        lines.append(
            "  4. Browser click-through of the changed surface at http://localhost:3000\n"
            "     (claude-in-chrome: navigate, exercise the page the change touched,\n"
            "     read_console_messages for errors)."
        )
    if "push" in pending:
        asked.append("push")
        lines.append(push_instruction(state))

    lines.append("")
    lines.append(
        "When a stage passes, clear it: "
        f"`python \"{(ROOT / '.claude' / 'hooks' / 'sector_loop.py').as_posix()}\" done "
        + " ".join(asked)
        + "`"
    )
    lines.append(
        "If a stage fails, fix the cause and stop again — the loop re-runs. "
        "Deploying to Railway is NOT part of this loop; see sector-app-test-deploy.md."
    )
    return "\n".join(lines)


def push_instruction(state: dict) -> str:
    git_info = state.get("git") or git_state()
    auto = os.environ.get("SECTOR_LOOP_PUSH", "").lower() == "auto"
    confirm = (
        "     Push without asking (SECTOR_LOOP_PUSH=auto)."
        if auto
        else "     ASK THE USER TO CONFIRM before pushing — this leaves the machine."
    )
    return (
        "  5. Push to the personal git repo — everything local is green:\n"
        f"     `git add -A` then `git commit` with a message describing the change,\n"
        f"     then `git push {git_info.get('remote', 'origin')} "
        f"{git_info.get('branch', 'HEAD')}`.\n"
        f"     Remote: {git_info.get('url', '(unknown)')}\n"
        f"{confirm}"
    )


def cmd_gate() -> int:
    if disabled():
        return 0
    read_input()  # drain stdin; stop_hook_active is not used — attempts cap the loop
    state = load_state()
    pending = ordered(state["pending"])
    if not pending:
        return 0

    if state["attempts"] >= MAX_ATTEMPTS:
        state["pending"] = []
        state["files"] = []
        state["attempts"] = 0
        save_state(state)
        emit(
            {
                "systemMessage": (
                    f"sector-app verify loop gave up after {MAX_ATTEMPTS} attempts; "
                    "state cleared. Re-run the stages by hand or edit a file to re-arm."
                ),
                "suppressOutput": True,
            }
        )
        return 0

    results, failed = [], False
    for stage in pending:
        runner = RUNNERS.get(stage)
        if runner is None:
            continue
        ok, output = runner()
        label = {"pytest": "1. backend pytest", "build": "2. frontend build"}[stage]
        if ok:
            results.append(f"  {label}: PASS")
            state["pending"] = [s for s in state["pending"] if s != stage]
        else:
            failed = True
            results.append(f"  {label}: FAIL\n{output}")
            break  # don't spend minutes on a build when the tests are already red

    # The push stage is only real once there is somewhere to push to. Until the
    # repo is initialized and a remote exists, drop it rather than blocking
    # every turn on a stage that cannot run.
    note = ""
    if "push" in state["pending"]:
        git_info = git_state()
        state["git"] = git_info
        if not git_info["ready"]:
            state["pending"] = [s for s in state["pending"] if s != "push"]
            note = f"push stage skipped: {git_info['why']} (see sector-app-test-deploy.md)"

    save_state(state)
    remaining = ordered(state["pending"])
    if not remaining:
        state["attempts"] = 0
        state["files"] = []
        save_state(state)
        message = "sector-app verify loop: all stages green."
        emit({"systemMessage": f"{message} {note}".strip(), "suppressOutput": True})
        return 0

    state["attempts"] += 1
    save_state(state)

    if failed:
        reason = (
            "sector-app verify loop failed:\n"
            + "\n".join(results)
            + "\n\nFix the failure, then stop again — the loop re-runs from stage 1."
        )
    else:
        # Hold the push back until every local stage is green.
        to_ask = remaining
        if "push" in remaining and any(s in remaining for s in LOCAL_STAGES):
            to_ask = [s for s in remaining if s != "push"]
        reason = instructions(state, to_ask, results)

    emit({"decision": "block", "reason": reason})
    return 0


# ------------------------------------------------------------------------ manual


def cmd_done(argv: list[str]) -> int:
    state = load_state()
    clear = set(argv) & set(STAGES) or set(AGENT_STAGES)
    state["pending"] = [s for s in state["pending"] if s not in clear]
    if not state["pending"]:
        state["attempts"] = 0
        state["files"] = []
    save_state(state)
    print(f"cleared: {', '.join(ordered(clear))}; pending: {', '.join(state['pending']) or 'none'}")
    return 0


def cmd_status() -> int:
    state = load_state()
    print(json.dumps(state, indent=2))
    return 0


def cmd_reset() -> int:
    save_state({"pending": [], "files": [], "attempts": 0, "signature": ""})
    print("loop state reset")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "stamp":
        return cmd_stamp()
    if mode == "gate":
        return cmd_gate()
    if mode == "done":
        return cmd_done(sys.argv[2:])
    if mode == "status":
        return cmd_status()
    if mode == "reset":
        return cmd_reset()
    print(__doc__)
    print("usage: sector_loop.py {stamp|gate|done [stage...]|status|reset}")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a broken hook must never wedge the session
        sys.stderr.write(f"sector_loop: {exc}\n")
        sys.exit(0)
