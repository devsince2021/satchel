"""`git commit` 명령 읽기와 커밋 제목 판정 — PreToolUse 훅 판정(`seam/libs/block.py`)이 Bash 명령마다 부른다.

- `commits(cmd, cwd)`: 명령 안의 `git commit`마다 `Commit`(제목·읽지 못한 까닭·자리). 명령은 Bash 판정과 같은 방식으로 풀어 읽는다
  (`seam/libs/bash.py`의 `walk` — 조각·`cd`·변수·감싸는 명령, `$( … )`·백틱·`eval`·`sh -c`·셸 본문(heredoc·스크립트 파일) 안까지).
  `-m "$(cat <<'EOF' … EOF)"` 꼴은 heredoc 본문을 메시지로 읽는다(끝말에 따옴표가 있거나 본문에 `$`·백틱이 없을 때).
- 제목 = 첫 `-m`(`-m<글>`·`--message=<글>`·`--message <글>`·`-am <글>`처럼 짧은 깃발 무리 끝의 `m` 포함)의 첫 비지 않은 줄.
- 제목을 읽을 수 없는 꼴(`Commit.unreadable`): `-m` 없이 편집기를 여는 커밋, `-e`/`--edit`, `-F`/`--file`, `-C`/`-c`/`--reuse-message`/
  `--reedit-message`, `--fixup`/`--squash`(제목을 git이 만든다), 펼 수 없는 치환(`$`·백틱)이 남은 제목.
  `--amend --no-edit`(`-m` 없음)은 지금 HEAD 제목을 그대로 쓰므로 `Commit.amend_keep` — 부르는 쪽이 HEAD 제목을 읽어 판정한다.
- `work_problem(work, title)`: 작업 세션 — 흐름 규칙(`src/rules/flow.json`) 꼴 `<ID> <단계>:`(이 작업 ID, 있는 단계, 작업 세션이 찍는
  단계, 할 일 번호 필수 단계의 `#N`). 판정은 `seam/libs/commits.py`의 `title_problem` — 끝 확인과 한 자리.
- `lead_problem(cfg, commit, added)`: 리드 세션(작업 세션이 아닌 세션, seam 설정이 있는 저장소) — 제목이 작업 ID로 시작하면 같은 꼴과
  리드가 찍는 단계(`req` — `merge`는 부명령 join만 남긴다), 요구사항 파일을 새로 더하는 커밋은 그 ID가 제목에 있어야 한다.
"""
import os
import re
import shlex

from seam.libs import bash, config, rules, steplog
from seam.libs import commits as history  # 커밋 제목 판정 한 자리(끝 확인과 같이 씀) — 이 모듈의 `commits()`와 이름이 겹쳐 바꿔 부른다

CAT_HEREDOC = re.compile(r"\"\$\(\s*cat\s+<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[ \t]*\n(.*?)\n[ \t]*\2[ \t]*\n\s*\)\"", re.S)
VALUE_SHORT = "mFCct"  # 값을 받는 짧은 깃발(-m 메시지, -F 파일, -C/-c 다시 쓰기, -t 틀)
OPTIONAL_SHORT = "uS"  # 값을 붙여서만 받는 짧은 깃발(-u<모드>·-S<키>) — 무리의 나머지는 값
LONG_VALUE = ("--message", "--file", "--reuse-message", "--reedit-message", "--template", "--author", "--date", "--cleanup",
              "--fixup", "--squash", "--trailer", "--pathspec-from-file")
LONG_FLAGS = ("--amend", "--no-edit", "--edit", "--all", "--allow-empty", "--allow-empty-message", "--quiet", "--verbose",
              "--no-verify", "--signoff", "--only", "--include", "--patch", "--dry-run", "--short", "--porcelain", "--long",
              "--null", "--no-status", "--status", "--reset-author", "--no-gpg-sign", "--no-post-rewrite", "--interactive")
DYNAMIC = re.compile(r"\$[A-Za-z_{(]|`|" + re.escape(bash.SUB_MARK))
TELL = "`git commit -m \"<제목>\"`로 쓴다(제목은 첫 `-m`의 첫 줄)"


class Commit:
    """명령 안 `git commit` 하나 — 제목(title, 못 읽으면 None)·못 읽은 까닭(unreadable)·`--amend --no-edit`(amend_keep)·
    git이 도는 자리(where, 모르면 None)."""

    def __init__(self, title=None, unreadable=None, amend_keep=False, where=None):
        self.title, self.unreadable, self.amend_keep, self.where = title, unreadable, amend_keep, where


def _long(name):
    """git이 받는 모호하지 않은 긴 옵션 줄임 → 온 이름(모르면 그대로)."""
    hits = [o for o in LONG_VALUE + LONG_FLAGS if o.startswith(name)] if len(name) > 2 else []
    return name if name in LONG_VALUE + LONG_FLAGS else (hits[0] if len(hits) == 1 else name)


def read_args(args):
    """`git commit` 뒤 인자 → Commit(자리 없이)."""
    msgs, why, amend, no_edit, edit = [], None, False, False, False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            name = _long(name)
            if name in LONG_VALUE and not eq:
                val = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if name == "--message":
                msgs.append(val)
            elif name == "--file":
                why = why or "-F/--file — 파일에서 읽는 메시지"
            elif name in ("--reuse-message", "--reedit-message"):
                why = why or "-C/-c — 다른 커밋 메시지를 다시 씀"
            elif name in ("--fixup", "--squash"):
                why = why or f"{name} — 제목을 git이 만든다"
            elif name == "--amend":
                amend = True
            elif name == "--no-edit":
                no_edit = True
            elif name == "--edit":
                edit = True
        elif a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                c = a[j]
                if c in VALUE_SHORT:
                    val = a[j + 1:]
                    if not val:
                        val = args[i + 1] if i + 1 < len(args) else ""
                        i += 1
                    if c == "m":
                        msgs.append(val)
                    elif c == "F":
                        why = why or "-F/--file — 파일에서 읽는 메시지"
                    elif c in "Cc":
                        why = why or "-C/-c — 다른 커밋 메시지를 다시 씀"
                    break
                if c in OPTIONAL_SHORT:
                    break
                if c == "e":
                    edit = True
                j += 1
        i += 1
    if why:
        return Commit(unreadable=why)
    if edit:
        return Commit(unreadable="-e/--edit — 편집기를 연다")
    if not msgs:
        if amend and no_edit:
            return Commit(amend_keep=True)
        return Commit(unreadable="-m 없음 — 편집기를 연다")
    # 줄 나눔: 조각 나누기(`bash.walk`)가 줄바꿈을 따옴표 안에서도 ` ; `로 바꾼다 — 둘 다 줄 끝으로 본다
    lines = [ln.strip() for ln in re.split(r"\n| ; ", msgs[0]) if ln.strip()]
    if not lines:
        return Commit(unreadable="첫 -m이 비었다")
    if DYNAMIC.search(lines[0]):
        return Commit(unreadable="제목에 펼 수 없는 치환($·백틱)이 남았다")
    return Commit(title=lines[0])


def _git_where(tokens, base):
    """git 전역 옵션 `-C`로 옮긴 자리(모르면 None)와 하위 명령 뒤 인자."""
    args, i, where = tokens[1:], 0, base
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        flag = a.split("=", 1)[0] if a.startswith("--") else a[:2]
        has = ("=" in a) if a.startswith("--") else len(a) > 2
        if flag in bash.GIT_GLOBALS_WITH_VALUE:
            value = (a.split("=", 1)[1] if a.startswith("--") else a[2:]) if has else (args[i + 1] if i + 1 < len(args) else "")
            if flag == "-C":
                if "$" in value or "`" in value or (where is None and not value.startswith("/")):
                    where = None
                else:
                    where = bash.resolve(value, where or "/")
            i += 1 if has else 2
        else:
            i += 1
    return where, args[i + 1:] if i < len(args) else []


def _inline_heredocs(cmd):
    """`"$(cat <<'E' … E)"`를 본문(셸 따옴표)으로 — 끝말에 따옴표가 있거나 본문에 `$`·백틱이 없을 때만."""
    def sub(m):
        quoted, body = bool(m.group(1)), m.group(3)
        return shlex.quote(body) if quoted or not re.search(r"[$`]", body) else m.group(0)
    return CAT_HEREDOC.sub(sub, cmd)


def commits(cmd, cwd, depth=0, env=None):
    """명령 안 `git commit`마다 Commit. 나눌 수 없는 명령은 [](Bash 판정 `bash.reason`이 막는다)."""
    cmd = _inline_heredocs(cmd)
    out = []
    if depth < 3:
        for inner in bash._unescaped_subs(bash.drop_heredoc_bodies(cmd, quoted_only=True)):
            out += commits(inner, cwd, depth + 1, env)
    env = bash.new_env(env)
    try:
        entries = bash.walk(cmd, cwd, env)
    except ValueError:
        return out
    made = None
    for _, tokens, _, base, _ in entries:
        name = os.path.basename(tokens[0])
        if name == "git":
            if bash._git_sub(tokens[1:]) == "commit":
                where, rest = _git_where(tokens, base)
                found = read_args(rest)
                found.where = where
                out.append(found)
            continue
        if depth >= 3:
            continue
        if name == "eval":
            out += commits(" ".join(tokens[1:]), base or cwd, depth + 1, env)
        elif name in bash.SHELLS and any(t.startswith("-") and not t.startswith("--") and "c" in t[1:] for t in tokens[1:]):
            for j, t in enumerate(tokens[1:], 1):
                if t.startswith("-") and not t.startswith("--") and "c" in t[1:] and j + 1 < len(tokens):
                    out += commits(tokens[j + 1], base or cwd, depth + 1, env)
                    break
        elif bash._script_target(tokens):
            if made is None:
                made = bash._heredoc_scripts(entries, cmd)
            for body in bash._shell_bodies(tokens, cmd, base, made):
                out += commits(body, base or cwd, depth + 1, env)
    return out


def head_title(where):
    """`where` 저장소 HEAD 제목(`--amend --no-edit`이 그대로 쓸 제목). 못 읽으면 None."""
    from libs import git as gitlib
    try:
        return gitlib.run(where, "log", "-1", "--format=%s", "HEAD", timeout=10).strip() or None
    except (gitlib.GitError, OSError):
        return None


def work_problem(work, commit, ctx=None, record=None):
    """작업 세션 커밋 판정 — 막을 까닭 또는 None. ctx·record(세션 기록)가 있으면 단계 확인도: 단계 사슬의 앞 단계 커밋이 있나
    (`commits.chain_problem` — `seam step`·끝 확인과 같은 판정), 그 단계를 `seam step <단계>`로 들어왔나(세션 기록 자리 `steps.json`의
    시작한 단계 목록). 단계 기록이 없으면 시작하지 않은 것이고, 깨졌으면 예외(부른 쪽이 막는다 — 기록이 없다고 지나가지 않는다)."""
    title = commit.title
    if commit.amend_keep:
        title = head_title(commit.where) if commit.where else None
        if title is None:
            return f"`git commit --amend --no-edit`이 그대로 쓸 HEAD 제목을 읽지 못했다 — {TELL}."
    if title is None:
        return f"커밋 제목을 읽을 수 없다({commit.unreadable}) — {TELL}. 꼴은 `{work} <단계>: …`."
    found = history.title_problem(work, title, "작업 세션")
    if found:
        return f"커밋 제목 `{title}`: {found}"
    if ctx is None or record is None:
        return None
    flow = rules.flow()
    step = flow.title_re(work, flow.names, bundle=True).match(title).group(1)
    found = history.chain_problem(ctx, work, step)
    if found:
        prev = flow.prerequisite(step)
        return (f"커밋 `{title}`: {found}. 먼저 {prev} 단계를 마치고 `{flow.title(work, prev)} …`로 커밋한다"
                f"(`python3 {config.ENTRY} step {prev}`).")
    if step not in steplog.read_steps(record["session_dir"])["started"]:  # 단계 기록 읽기는 시작 명령과 한 자리
        return (f"커밋 `{title}`: {step} 단계를 시작 명령으로 들어오지 않았다 — 먼저 `python3 {config.ENTRY} step {step}`를 불러 "
                "앞 단계 확인과 그 단계 안내를 받은 뒤 커밋한다.")
    return None


def lead_problem(cfg, commit, added):
    """리드 세션 커밋 판정 — 막을 까닭 또는 None. added: 이번 커밋에 새로 들어가는 요구사항 파일의 작업 ID들(못 읽었으면 ()).
    제목을 못 읽는 커밋(편집기 등)은 요구사항 파일을 더할 때만 막는다 — 그 밖의 리드 커밋은 묶지 않는다."""
    flow = rules.flow()
    title = commit.title
    if commit.amend_keep:
        title = head_title(commit.where) if commit.where else None
    ids = re.match(rf"((?:{flow.other_id}{re.escape(flow.bundle_sep)})*)({config.ID_PATTERN})"
                   rf"((?:{re.escape(flow.bundle_sep)}{flow.other_id})*)\s", title or "")
    if ids:
        found = history.title_problem(ids.group(2), title, "리드")
        if found:
            return f"커밋 제목 `{title}`: {found}"
    named = set(re.findall(config.ID_PATTERN, ids.group(0))) if ids else set()
    missing = [w for w in added if w not in named]
    if missing:
        req = flow.title(missing[0], flow.lead_steps[0])
        why = f"제목을 읽을 수 없다({commit.unreadable})" if title is None else f"제목 `{title}`이 {', '.join(missing)}로 시작하지 않는다"
        return (f"이 커밋은 요구사항 파일({', '.join(missing)})을 새로 더하는데 {why} — `git commit -m \"{req} …\"`로 쓴다"
                "(작업 세션 열기가 이 커밋을 찾는다).")
    return None
