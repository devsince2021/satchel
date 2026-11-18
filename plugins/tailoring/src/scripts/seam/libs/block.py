"""도구 호출 막기 판정 — 부명령 `guard`(PreToolUse 훅, `seam/commands/guard.py`)가 작업 세션에서 부른다.

- AskUserQuestion: 막는다 — 작업 세션은 사용자에게 묻지 않고 리드에게 결정 요청을 보낸다.
- Agent·Task: 프롬프트가 하위 에이전트 공용 머리말(`src/skills/seam/subagent-header.md`의 ``` 블록 첫 줄)로 시작하거나
  "…subagent-header.md를 읽고 따르라" 줄을 담아야 한다. 머리말 자리표(`{WORKTREE}` 등)가 남으면 막는다.
- Bash: `bash.reason`(git 되돌리기류·리드 저장소 쓰기·셸 매개변수 가공·인터프리터 본문 git 쓰기, 리드 저장소는 세션 기록
  `lead_top`), `bash.gate_reason`(세션 기록 `block_git`·`block_git_args` — feed가 규칙 `src/rules/git.json`에서 만들어 적는다),
  glob 뒤 `..`(`bash.glob_dotdot_words`), deny에 걸리는 읽기·쓰기(`bash.deny_read_hits`·`deny_write_hits`). deny 규칙은
  세션 settings(세션 기록 `settings`)와 `CLAUDE_CONFIG_DIR`(없으면 `~/.claude`)의 settings.json·settings.local.json에서 읽는다.
  그 뒤 `git commit`의 제목(`seam/libs/gitcommit.py` — 흐름 규칙 꼴 `<ID> <단계>:`, 이 작업 ID, 작업 세션 단계, 읽을 수 없는 꼴은 막음)과
  단계 확인(앞 단계 커밋, `seam step <단계>`로 들어왔나 — 세션 기록 `steps.json`).
작업 세션의 Agent·AskUserQuestion 판정 예외는 지나가고(한 줄), Bash 판정 예외는 막음(fail-closed).
리드 세션(작업 세션이 아닌 세션, seam 설정이 있는 저장소)은 `lead_judge` — `git commit`만 좁게 본다. 판정 예외는 지나간다(한 줄).
"""
import json
import os
import re
import sys

from seam.libs import config

JUDGED = ("Agent", "Task", "AskUserQuestion", "Bash")
HEADER = os.path.join(config.PLUGIN_ROOT, "src", "skills", "seam", "subagent-header.md")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _block(header):
    m = re.search(r"```\n(.*?)```", _read(header), re.S)
    return m.group(1) if m else ""


def header_marker(header=HEADER):
    return _block(header).split("\n", 1)[0].strip()


def placeholders(header=HEADER):
    return sorted(set(re.findall(r"\{[A-Z_]+\}", _block(header))))


def read_line(header=HEADER):
    """"먼저 …<머리말 파일 이름>을 읽고 따르라" 줄 — 막는 글이 권하는 줄과 왕복한다."""
    return re.compile(re.escape(os.path.basename(header)) + r"`?\s*(?:을|를)\s*읽고\s*따르")


def agent_problem(prompt, header=HEADER):
    left = [p for p in placeholders(header) if p in prompt]
    if left:
        return f"Agent 프롬프트에 머리말 자리표 {', '.join(left)}가 남았다. 채워서 다시 띄운다."
    marker = header_marker(header)
    if not marker:
        raise ValueError(f"머리말 {header}에 ``` 블록이 없다")
    if prompt.lstrip().startswith(marker) or read_line(header).search(prompt):
        return None
    return (f"Agent 프롬프트가 공용 머리말로 시작하지 않는다. `{header}`의 ``` 블록을 자리표를 채워 맨 위에 붙이거나 "
            f"\"먼저 `{header}`를 읽고 따르라\" 줄을 넣어 다시 띄운다.")


ASK = ("작업 세션은 사용자에게 직접 묻지 않는다. 결정이 필요하면 선택지·권장·이유·틀렸을 때 비용을 결정 파일로 워크트리에 쓰고 "
       "리드에게 `[<작업 ID> → <리드>] 결정 요청: <경로>`를 SendMessage로 보낸 뒤 `대기: 리드 — 결정 요청`으로 턴을 끝낸다"
       "(사용자는 리드까지만 대화한다).")


def load_deny_rules(settings_file=None, home=None):
    """`CLAUDE_CONFIG_DIR`(없으면 home, 그것도 없으면 `~/.claude`)의 settings.json·settings.local.json과 settings_file의 deny."""
    home = os.environ.get("CLAUDE_CONFIG_DIR") or home or os.path.expanduser("~/.claude")
    files = [os.path.join(home, name) for name in ("settings.json", "settings.local.json")]
    rules = []
    for path in files + ([settings_file] if settings_file else []):
        try:
            with open(path, encoding="utf-8") as f:
                found = (json.load(f).get("permissions") or {}).get("deny") or []
        except (OSError, ValueError, AttributeError):
            continue
        rules.extend(r for r in found if isinstance(r, str))
    return rules


def bad_git_args(args):
    """`<하위>:<인자>` 꼴이 아닌 값들."""
    return [a for a in args if not isinstance(a, str) or a.count(":") != 1 or not all(a.split(":"))]


def bash_problem(cmd, cwd, rules, record, work=None, ctx=None):
    """작업 세션 Bash 판정 — 막을 까닭 또는 None. 판정 중 예외는 부른 쪽이 막음으로 바꾼다."""
    from seam.libs import bash  # 무거운 모듈 — 작업 세션의 Bash에서만 읽는다
    found = bash.reason(cmd, record["lead_top"], cwd)
    if found:
        return found
    block_git = tuple(record.get("block_git") or ())
    block_git_arg = tuple(record.get("block_git_args") or ())
    bad = bad_git_args(block_git_arg)
    if bad:
        return f"세션 기록의 block_git_args 꼴은 <하위>:<인자>다({', '.join(map(str, bad))}) — 막음. 규칙 src/rules/git.json의 args를 고치고 세션을 다시 연다"
    found = bash.gate_reason(cmd, cwd, block_git, block_git_arg=block_git_arg)
    if found:
        return found
    hits = bash.glob_dotdot_words(cmd)
    if hits:
        return ("Bash 경로 낱말에 glob 뒤 `..`이 있다: " + "; ".join(hits[:3]) +
                ". 이 꼴은 셸이 펼친 뒤에야 경로가 정해져 Claude Code가 bypass에서도 확인 창을 띄워 멈춘다 — "
                "glob 없이 경로를 적어라(예: find로 찾은 뒤 그 경로를 그대로, 또는 `..`을 걷은 위 디렉터리를 바로).")
    hits = bash.deny_read_hits(cmd, cwd, rules)
    if hits:
        return ("Bash가 settings deny로 읽기를 막은 경로를 건드린다: " + "; ".join(hits[:3]) +
                ". 그 경로는 이 세션이 읽지 않는다 — 필요하면 리드에게 묻는다.")
    hits = bash.deny_write_hits(cmd, cwd, rules)
    if hits:
        return ("Bash가 settings deny로 편집을 막은 경로에 쓴다: " + "; ".join(hits[:3]) +
                ". 그 경로는 이 세션이 고치지 않는다 — 고쳐야 하면 리드에게 알린다.")
    if work and "commit" in cmd:
        from seam.libs import gitcommit
        for found in gitcommit.commits(cmd, cwd):
            problem = gitcommit.work_problem(work, found, ctx, record)
            if problem:
                return problem
    return None


def staged_requirements(where, cfg):
    """`where` 저장소에서 이번 커밋에 새로 들어가는(스테이징된 추가) 요구사항 파일 `<seam.pieces>/<ID>-<슬러그>/requirements.md`의
    작업 ID들. 자리를 모르거나 git이 실패하면 ()(읽지 못함 — 지나간다)."""
    from libs import git as gitlib
    if not where:
        return ()
    try:
        top = gitlib.run(where, "rev-parse", "--show-toplevel", timeout=10).strip()
        names = gitlib.run(top, "diff", "--cached", "--name-only", "--diff-filter=A", "-z", timeout=10).split("\0")
    except (gitlib.GitError, OSError):
        return ()
    shape = re.compile(rf"{re.escape(cfg.rel('pieces').strip('/'))}/({config.ID_PATTERN})-[^/]+/requirements\.md")
    return tuple(dict.fromkeys(m.group(1) for n in names if (m := shape.fullmatch(n))))


def lead_judge(payload):
    """작업 세션이 아닌 세션(리드 세션)의 Bash — seam 설정(`.studio/tailoring.json`)이 있는 저장소의 `git commit`만 본다:
    작업 ID로 시작하는 제목의 흐름 꼴·리드 단계, 요구사항 파일을 새로 더하는 커밋의 ID. 그 밖은 None. 설정 오류 등 판정 예외는
    부른 쪽(`guard`)이 판정 불가로 지나간다(한 줄). 작업 세션용 막기(금지 목록·질문 창·deny 등)는 걸지 않는다."""
    if payload.get("tool_name") != "Bash":
        return None
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if "commit" not in cmd:
        return None
    cwd = payload.get("cwd") or os.getcwd()
    root = config.project_root(cwd)
    if not root or not config.present(root):
        return None
    cfg = config.load(root)
    from seam.libs import gitcommit
    for found in gitcommit.commits(cmd, cwd):
        problem = gitcommit.lead_problem(cfg, found, staged_requirements(found.where, cfg))
        if problem:
            return problem
    return None


def judge(payload, found_session, deny_rules=None):
    """막을 까닭 또는 None. found_session은 `session.work_session`의 값(작업 세션이 아니면 None)."""
    if found_session is None:
        return None
    ctx, work, record = found_session
    tool = payload.get("tool_name")
    inp = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    if tool == "Bash":
        try:
            rules = load_deny_rules(record.get("settings"), record.get("home")) if deny_rules is None else deny_rules
            return bash_problem(inp.get("command") or "", cwd, rules, record, work, ctx)
        except Exception as e:  # noqa: BLE001  판정 중 예외는 막음(fail-closed)
            return f"명령을 판정하지 못했다({type(e).__name__}) — 막음. 명령을 나눠 다시 낸다."
    try:
        if tool in ("Agent", "Task"):
            return agent_problem(inp.get("prompt") or "")
        if tool == "AskUserQuestion":
            return ASK
    except Exception as e:  # noqa: BLE001  Agent 판정 예외는 통과, 한 줄만 남긴다
        sys.stderr.write(f"[pre_tool] 판정 불가로 통과: {type(e).__name__}: {e}\n")
    return None
