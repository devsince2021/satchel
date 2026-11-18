"""작업 세션 프로세스 찾기와 새 프로세스로 부르는 끝 확인 — 부명령 `join`이 쓴다.

- `session_pids`·`name_pattern`: `claude --name <세션 이름>`으로 뜬 작업 세션 프로세스(`pgrep -f`, 없으면 모른다고 보고 []).
- `session_running`: 명령 줄에 세션 settings 경로가 든 프로세스가 있나(합친 뒤 작업 세션 claude가 멈추기 기다림).
- `inspect_problem`: 작업 워크트리에서 끝 확인(`<입구> inspect <ID>`)을 새 프로세스로 — 통과면 None.
"""
import os
import re
import subprocess
import sys


def inspect_problem(entry, worktree, work):
    """작업 워크트리에서 `<entry> inspect <work>`가 통과하지 않으면 그 출력, 통과면 None."""
    if not os.path.exists(entry):
        return f"입구가 없다: {entry}"
    out = subprocess.run([sys.executable, entry, "inspect", work], cwd=worktree, capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        return f"끝 확인(inspect)이 통과하지 않는다(종료 {out.returncode}). 작업 세션에 돌려보낸다:\n{out.stdout}{out.stderr}".rstrip()
    return None


def session_running(marker):
    """명령 줄에 marker(세션 settings 경로)가 든 프로세스가 있나 — 작업 세션 claude가 아직 도는지(시험이 가짜로 바꾼다).
    pgrep이 없으면 모른다고 보고 False."""
    try:
        return subprocess.run(["pgrep", "-f", marker], capture_output=True).returncode == 0
    except OSError:
        return False


def name_pattern(title):
    """`pgrep -f`(확장 정규식)로 `--name <title>` 표지를 찾는 꼴 — 뒤는 빈칸이나 끝(`piece P-07`이 `piece P-077`에 걸리지 않게)."""
    return "--name " + re.sub(r"([.\[\]()*+?{}|^$\\])", r"\\\1", title) + "( |$)"


def session_pids(title):
    """`claude --name <title>`로 뜬 작업 세션 프로세스 pid들(feed가 띄운 명령·찍어 준 명령 모두 이 표지를 쓴다).
    시험이 가짜로 바꾼다. pgrep이 없으면 모른다고 보고 []."""
    try:
        out = subprocess.run(["pgrep", "-f", "--", name_pattern(title)], capture_output=True, text=True)  # 꼴이 `-`로 시작한다
    except OSError:
        return []
    return out.stdout.split() if out.returncode == 0 else []
