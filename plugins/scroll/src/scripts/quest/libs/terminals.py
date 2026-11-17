"""작업 세션을 띄우고 닫는 터미널 — 설정 `session.terminal`이 고른 것을 돌린다.

- 프리셋(`src/presets/terminals.json`, 읽기는 `quest/libs/presets.py`): `launch`가 없는 프리셋(`none`)은 띄울 명령만 찍는다.
  있는 프리셋은 열기 전에 실행 파일(`bin` — PATH, 없으면 `fallbacks`)과 환경 변수(`env`)를 보고, 띄우기 명령(글 목록 — 셸을 거치지
  않는다)을 돌려 핸들을 꺼낸다(`handle`의 차례대로 — `json` 경로·`regex`·`last_line`). 못 꺼내면 `find`(목록 명령에서 title로 찾기)를
  몇 번 다시 해 보고, 끝내 없으면 `lost` 글을 기록·알림으로 남긴다(세션은 떴을 수 있어 열기를 되돌리지 않는다).
  닫기는 `close`의 명령들을 차례로(실패해도 이어 간다), 핸들이 없으면 건너뛴다.
- `custom`: 설정 `session.launch`·`session.close` 셸 명령 틀(`config.fill` — 자리표는 셸 따옴표로 싼다). 띄우기의 마지막 출력 줄이 핸들.

open·merge는 이 모듈만 거쳐 띄우고 닫는다. 시험은 `run`·`sleep`·`which`를 바꾼다.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time

from quest.libs import config, presets

LAUNCH_TIMEOUT = 60
CLOSE_TIMEOUT = 60


class TerminalError(Exception):
    pass


def _run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)


run = _run  # 시험이 바꾼다
sleep = time.sleep  # 시험이 바꾼다
which = shutil.which  # 시험이 바꾼다


def preset(name):
    """이름의 프리셋 사전, custom이면 None."""
    return None if name == presets.CUSTOM else presets.terminals().presets[name]


def find_bin(spec):
    """실행 파일 자리 — PATH의 이름, 없으면 fallbacks 가운데 실행할 수 있는 첫 자리. 없으면 None."""
    found = which(spec["name"])
    if found:
        return found
    return next((p for p in spec["fallbacks"] if os.path.isfile(p) and os.access(p, os.X_OK)), None)


def problems(name, environ=None):
    """열기 전에 막을 까닭들 — 프리셋의 실행 파일이 없거나 필요한 환경 변수가 없으면."""
    environ = os.environ if environ is None else environ
    p = preset(name)
    if p is None or p["launch"] is None:
        return []
    out = []
    if find_bin(p["bin"]) is None:
        where = "·".join([f"PATH의 {p['bin']['name']}", *p["bin"]["fallbacks"]])
        out.append(f"터미널 {name}: 실행 파일이 없다({where}) — 설치하거나 설정 session.terminal을 바꾼다")
    for var, why in p["env"].items():
        if not environ.get(var):
            out.append(f"터미널 {name}: {why}")
    return out


def _values(p_open, bin_path=""):
    return {"bin": bin_path, "title": p_open["title"], "command": p_open["command"], "worktree": p_open["worktree"],
            "id": p_open["work"]}


def custom_values(p_open):
    """custom 띄우기 틀의 자리표 값(README 표의 자리표)."""
    return {"command": p_open["command"], "worktree": p_open["worktree"], "id": p_open["work"], "title": p_open["title"],
            "settings": p_open["settings"], "prompt_file": p_open["prompt_file"], "lead": p_open["lead_name"],
            "branch": p_open["branch"]}


def launch_line(name, cfg, p_open):
    """띄울 명령을 사람이 읽는 셸 한 줄로(`--dry-run`) — 띄우지 않는 프리셋이면 None. 실행 파일·환경 변수가 없으면 그 자리를 이름으로 둔다."""
    p = preset(name)
    if p is None:
        return config.fill(cfg.get("session.launch"), custom_values(p_open))
    if p["launch"] is None:
        return None
    env = {k: os.environ.get(k) or f"<{k}>" for k in p["env"]}
    argv = presets.fill_argv(p["launch"], _values(p_open, find_bin(p["bin"]) or p["bin"]["name"]), env)
    return " ".join(shlex.quote(a) for a in argv)


def _dig(data, dotted):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def extract_handle(ways, stdout, stderr=""):
    """핸들 꺼내기 — ways의 차례대로 처음 나온 것. 없으면 None."""
    for way in ways:
        kind, value = next(iter(way.items()))
        if kind == "json":
            try:
                found = _dig(json.loads(stdout), value)
            except ValueError:
                found = None
            if isinstance(found, str) and found.strip():
                return found.strip()
        elif kind == "regex":
            m = re.search(value, stdout + "\n" + stderr)
            if m:
                return m.group(0)
        elif kind == "last_line":
            lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
            if lines and re.fullmatch(value, lines[-1]):
                return lines[-1]
    return None


def _find(p, values, title):
    """목록 명령에서 title로 핸들을 찾는다(find.tries번, 사이에 wait_seconds) — 없으면 None."""
    spec = p["find"]
    argv = presets.fill_argv(spec["argv"], values)
    for i in range(spec["tries"]):
        if i:
            sleep(spec["wait_seconds"])
        try:
            out = run(argv, LAUNCH_TIMEOUT)
            items = _dig(json.loads(out.stdout), spec["list"]) if out.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            items = None
        hits = [it.get(spec["handle"]) for it in items or () if isinstance(it, dict) and it.get(spec["title"]) == title]
        hits = [h for h in hits if isinstance(h, str) and h.strip()]
        if hits:
            return hits[-1].strip()
    return None


def launch(name, cfg, p_open):
    """띄운다. 돌려주는 것 {"handle": 글|None, "note": 글|None} — 띄우지 않는 프리셋이면 None.
    띄우기 명령이 실패하면(부를 수 없음·종료 코드 0 아님·시간 초과) TerminalError."""
    p = preset(name)
    if p is None:
        line = config.fill(cfg.get("session.launch"), custom_values(p_open))
        try:
            out = run(["sh", "-c", line], LAUNCH_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise TerminalError(f"세션 띄우기 명령을 부르지 못했다: {e}") from e
        if out.returncode != 0:
            raise TerminalError(f"세션 띄우기 명령이 실패했다(종료 {out.returncode}): {line}\n{out.stdout}{out.stderr}")
        lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        return {"handle": lines[-1] if lines else None, "note": None}
    if p["launch"] is None:
        return None
    bin_path = find_bin(p["bin"])
    if bin_path is None:
        raise TerminalError(problems(name)[0])
    values = _values(p_open, bin_path)
    try:
        argv = presets.fill_argv(p["launch"], values)
    except KeyError as e:
        raise TerminalError(f"터미널 {name}: 환경 변수 {e.args[0]}가 없다") from e
    try:
        out = run(argv, LAUNCH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TerminalError(f"세션 띄우기 명령을 부르지 못했다: {e}") from e
    if out.returncode != 0:
        shown = " ".join(shlex.quote(a) for a in argv)
        raise TerminalError(f"세션 띄우기 명령이 실패했다(종료 {out.returncode}): {shown}\n{out.stdout}{out.stderr}")
    handle = extract_handle(p["handle"], out.stdout or "", out.stderr or "")
    if handle is None and p["find"]:
        handle = _find(p, values, p_open["title"])
    return {"handle": handle, "note": None if handle else f"터미널 {name}: 핸들을 받지 못했다 — {p['lost']}"}


def close_values(record):
    return {"id": record["work"], "title": record.get("title") or "", "worktree": record["worktree"],
            "handle": record.get("handle") or "", "branch": record["branch"], "settings": record.get("settings") or ""}


def close_plan(record, cfg):
    """닫기 차례 — (보일 줄들, 돌릴 것들 [(argv, 보일 줄)]) 또는 건너뛸 까닭(글). 세션을 연 프리셋(세션 기록 `terminal`)을 따른다."""
    name = record.get("terminal") or cfg.terminal
    if name == presets.CUSTOM:
        if cfg.terminal != presets.CUSTOM or not cfg.get("session.close"):
            return f"설정 session.close가 없어 건너뜀(연 터미널 {name})"
        line = config.fill(cfg.get("session.close"), close_values(record))
        return [(["sh", "-c", line], line)]
    if name not in presets.terminals().presets:
        return f"세션 기록의 터미널 {name}을 프리셋 src/presets/terminals.json에서 모른다 — 건너뜀"
    p = preset(name)
    if p["launch"] is None or not p["close"]:
        return f"터미널 {name}은 닫기가 없어 건너뜀"
    if not record.get("handle"):
        return f"세션 기록에 handle이 없어 건너뜀(터미널 {name}) — 창·탭은 손으로 닫는다"
    bin_path = find_bin(p["bin"])
    if bin_path is None:
        return f"터미널 {name}: 실행 파일이 없어 건너뜀"
    values = {**close_values(record), "bin": bin_path}
    out = []
    for step in p["close"]:
        try:
            argv = presets.fill_argv(step, values)
        except KeyError as e:
            return f"터미널 {name}: 닫기에 쓸 환경 변수 {e.args[0]}가 없어 건너뜀"
        out.append((argv, " ".join(shlex.quote(a) for a in argv)))
    return out


def close(record, cfg):
    """닫는다 — 경고 줄들(실패해도 이어 간다)."""
    plan = close_plan(record, cfg)
    if isinstance(plan, str):
        return [f"세션 닫기: {plan}"]
    warnings = []
    for argv, shown in plan:
        try:
            out = run(argv, CLOSE_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            warnings.append(f"경고: 세션 닫기 명령을 부르지 못했다: {shown}: {e}")
            continue
        if out.returncode != 0:
            warnings.append(f"경고: 세션 닫기 명령이 실패했다(종료 {out.returncode}): {shown}\n{out.stdout}{out.stderr}".rstrip())
    return warnings
