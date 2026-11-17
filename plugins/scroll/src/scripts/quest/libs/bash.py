"""작업 세션 Bash 명령 판정 — PreToolUse 훅 판정(`quest/libs/block.py`)이 작업 세션에서만 부른다. 표준 라이브러리만, Python 3.9 이상.

판정 함수(모두 막을 까닭 글 또는 None·목록을 돌려준다):
- `reason(cmd, lead, cwd)`: git 되돌리기류(`BLOCKED` 하위 명령, `reset --hard/--keep/--merge`, `branch` 지우기·옮기기,
  `-c alias.*`, 하위 명령 자리의 치환), 리드 저장소(`lead`)를 가리키는 git의 읽기 아닌 하위 명령(`-C`·`--git-dir`·
  `--work-tree`·`GIT_DIR`·`GIT_WORK_TREE`·앞선 `cd`로 자리를 정한다), 셸 매개변수 가공(`${x%…}` 등 — 셸 검사가 확인 창을
  띄워 세션이 멈춘다), 나눌 수 없는 명령, 인터프리터·셸 본문의 git 쓰기. `$( … )`·백틱·`sh -c`·`eval` 안도 본다.
- `gate_reason(cmd, cwd, block_git, block_git_arg=…)`: 켜는 깃발 — 셸 git 그 하위 명령(`block_git`)과
  그 하위 명령의 인자(`block_git_arg`, `<하위>:<인자>`). 따옴표 heredoc 본문은 글이라 보지 않는다.
- `glob_dotdot_words(cmd)`: glob 뒤 `..` 마디가 오는 경로 낱말(Claude Code가 bypass에서도 확인 창을 띄운다).
- `deny_read_hits(cmd, cwd, deny_rules)`·`deny_write_hits(cmd, cwd, deny_rules)`: settings `permissions.deny`의
  `Read(…)`·`Edit(…)`/`Write(…)`에 걸리는 읽기·쓰기 대상. 리다이렉션·tee·cp·sed -i·patch·git apply·인터프리터 본문
  (인라인·here-string·heredoc·스크립트 파일의 절대·`~` 경로)까지 대조하고, 데이터 자리 글자(출력·비교·데이터 상수)는 뺀다.

나눌 수 없거나 볼 수 없는 것은 막는 쪽(fail-closed). OS 경계가 아니다 — 같은 사용자 권한이라 훅을 거치지 않는 길은 남는다.
"""
import bisect
import functools
import glob
import itertools
import os
import re
import shlex
import sys

BLOCKED = {"checkout", "restore", "stash", "clean", "switch", "push", "worktree", "update-ref"}
READS = {"status", "log", "diff", "show", "rev-parse", "ls-files", "grep", "blame", "cat-file", "rev-list",
         "merge-base", "describe", "shortlog"}
# 감싸는 명령과 값을 받는 옵션. timeout은 옵션 뒤 시간 하나를 더 건넌다.
WRAPPERS = {"env": {"-u", "-C", "-S"}, "command": set(), "exec": {"-a"}, "nohup": set(), "time": set(), "builtin": set(),
            "nice": {"-n"}, "sudo": {"-u", "-g", "-C", "-h", "-p", "-U", "-D"}, "xargs": {"-I", "-n", "-P", "-L", "-s", "-E", "-d", "-a"},
            "timeout": {"-s", "-k"}, "stdbuf": {"-i", "-o", "-e"}}
UV_VALUE_OPTS = {"--with", "--python", "-p", "--project", "--directory", "--env-file", "--group", "--extra", "--package"}
KEYWORDS = {"{", "}", "!", "then", "do", "else", "elif", "if", "while", "until"}
# 셸 검사가 rm 여부를 못 가려 bypass에서도 확인창을 띄우는 매개변수 가공. ${x:-기본값} 꼴(:-·:=·:?·:+)은 둔다.
# 중괄호 없는 $m:u 꼴 zsh 수식어도 같다(뒤에 `:`가 붙는 변수는 ${m}: 로 감싼다).
PARAM_MANGLE = re.compile(r"\$\{\(|\$\{#?[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?(?:#|%|/|\^|,|:(?![-=?+]))"
                          r"|\$[A-Za-z_][A-Za-z0-9_]*:[A-Za-z]")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
GIT_GLOBALS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
GIT_PATH_FLAGS = {"-C", "--git-dir", "--work-tree"}
GIT_PATH_ENV = {"GIT_DIR", "GIT_WORK_TREE"}
BRANCH_MOVES = {"-d", "-D", "--delete", "-f", "--force", "-M", "-m", "--move", "-C", "--copy"}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", ";;", "|&"}
# `<<<`(here-string)은 heredoc이 아니다
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def _escaped(text, i):
    """text[i] 앞에 홀수 개 `\\`가 붙었나(셸이 펼치지 않는 `\\$(`·`` \\` ``)."""
    n = 0
    while i - n - 1 >= 0 and text[i - n - 1] == "\\":
        n += 1
    return n % 2 == 1


SUB_MARK = "$__SUB"


def hide_subs(text):
    """이스케이프되지 않은 `$( … )`를 안쪽부터 자리표 `$__SUB`(펼 수 없는 변수)로 바꾼다 — 낱말 나누기가 `(`에서 조각을 끊어
    뒤 명령을 앞 조각에 붙이지 않게. 안쪽은 `_unescaped_subs`로 따로 본다."""
    while True:
        found = [m for m in re.finditer(r"\$\(([^()]*)\)", text) if not _escaped(text, m.start())]
        if not found:
            return text
        for m in reversed(found):
            text = text[:m.start()] + SUB_MARK + text[m.end():]


def _blank_single_quoted(text):
    """큰따옴표 밖 작은따옴표 구간을 같은 길이의 빈칸으로 — 셸은 그 안 `$( … )`·백틱을 펼치지 않는다
    (`sed '…`x …`…'`의 백틱은 명령이 아니다). 큰따옴표 안 작은따옴표는 글자라 그대로 둔다."""
    out, quote = [], None
    for i, c in enumerate(text):
        if quote == "'":
            out.append(" " if c != "'" else "'")
            if c == "'":
                quote = None
            continue
        if quote == '"':
            out.append(c)
            if c == '"' and not _escaped(text, i):
                quote = None
            continue
        out.append(c)
        if c in "'\"" and not _escaped(text, i):
            quote = c
    return "".join(out)


def _unescaped_subs(text):
    """이스케이프되지 않은 `$( … )`(안에 괄호 없는 것)와 백틱 짝의 안쪽들. 작은따옴표 안은 셸이 펼치지 않으니 빼고 본다."""
    text = _blank_single_quoted(text)
    out = [m.group(1) for m in re.finditer(r"\$\(([^()]*)\)", text) if not _escaped(text, m.start())]
    ticks = [i for i, c in enumerate(text) if c == "`" and not _escaped(text, i)]
    out += [text[a + 1:b] for a, b in zip(ticks[::2], ticks[1::2])]
    return out


def drop_heredoc_bodies(cmd, quoted_only=False):
    """heredoc 본문 줄을 걷는다. quoted_only면 끝말이 따옴표로 감싸인(`<<'E'`·`<<"E"`) 본문만 — 셸이 펼치지 않는 글이라
    그 안 `$( … )`·백틱은 명령이 아니다. 따옴표 없는 본문은 셸이 펼치니 남긴다."""
    out, waiting = [], []
    for line in cmd.split("\n"):
        if waiting:
            dash, word, quoted = waiting[0]
            if (line.lstrip("\t") if dash else line) == word:
                waiting.pop(0)
                if not quoted_only or quoted:
                    continue
            elif not quoted_only or quoted:
                continue
            out.append(line)
            continue
        out.append(line)
        seen = _mask_quoted(line).replace(MASK["<"], " ") if quoted_only else line  # 따옴표 안 `<<'E'`는 시작이 아니다
        waiting = [(m.group(1) == "-", m.group(3), bool(m.group(2))) for m in HEREDOC.finditer(seen)]
    return "\n".join(out)


def _drop_comments(text):
    """따옴표 밖 낱말 첫 자리 `#`부터 그 줄 끝까지 걷는다. shlex 기본 주석은 줄바꿈을 ` ; `로 바꾼 뒤라
    파일 끝까지 삼킨다."""
    out, quote, i = [], None, 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i:i + 2])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c == "\\" and i + 1 < len(text):
            out.append(text[i:i + 2])
            i += 2
            continue
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or (text[i - 1] in " \t\n;&|(" and not _escaped(text, i - 1))):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        out.append(c)
        i += 1
    return "".join(out)


def segments(cmd):
    lex = shlex.shlex(_drop_comments(drop_heredoc_bodies(cmd)).replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
    lex.commenters = ""
    lex.whitespace_split = True
    part = []
    for tok in lex:
        if tok in SEPARATORS:
            if part:
                yield part
            part = []
        else:
            part.append(tok)
    if part:
        yield part


MASK = {"<": "\ue000", ">": "\ue001"}
UNMASK = str.maketrans({v: k for k, v in MASK.items()})


def _unmask(text):
    """따옴표 안에서 바꿔 둔 `<`·`>`를 원래 글자로."""
    return text.translate(UNMASK)


def _mask_quoted(text):
    """따옴표 안 `<`·`>`를 사용 영역 글자로 — 리다이렉션으로 보지 않는다. 셸 본문 재귀는 들어올 때 `_unmask`한다."""
    out, quote, i = [], None, 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i:i + 2])
                i += 2
                continue
            if c == quote:
                quote = None
            out.append(MASK.get(c, c))
        elif c == "\\" and i + 1 < len(text):
            out.append(text[i:i + 2])
            i += 2
            continue
        else:
            if c in "'\"":
                quote = c
            out.append(c)
        i += 1
    return "".join(out)


def segments_with_seps(cmd):
    """(조각, 뒤 구분자) 목록. `(`·`)`도 구분자로 낸다(빈 조각과 함께). `$'…'`는 `'…'`로.
    따옴표 안 `<`·`>`는 바꿔 둔다 — 토큰을 셸 본문으로 다시 넘기면 여기 들어올 때 되돌린다."""
    text = _mask_quoted(_drop_comments(drop_heredoc_bodies(_unmask(cmd))))
    text = re.sub(r"(?<!\\)((?:\\\\)*)\$'", r"\1'", text).replace(">|", ">")
    text = re.sub(r"(?<![\d&])>&(?=[^\d\-\s])", "> ", text)  # `>&파일`은 stdout·stderr를 파일로
    lex = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
    lex.commenters = ""
    lex.whitespace_split = True
    out, part = [], []
    for tok in lex:
        if tok in SEPARATORS:
            out.append((part, tok))
            part = []
        else:
            part.append(tok)
    out.append((part, ""))
    return out


SUBST = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand(tok, env):
    """`$X`·`${X}`를 변수표로 펼친다. 모르는 변수는 그대로 둔다."""
    def one(m):
        value = env.get(m.group(1) or m.group(2))
        return value if value is not None else m.group(0)
    return SUBST.sub(one, tok)


def _assignments(part):
    """조각이 변수 지정만이면 (이름, 값) 목록, 아니면 None."""
    pairs = []
    for t in part:
        name, eq, value = t.partition("=")
        if not eq or not name.isidentifier():
            return None
        pairs.append((name, value))
    return pairs


DECLARE = {"export", "declare", "typeset", "local", "readonly"}


def new_env(env=None):
    """변수표. 처음엔 HOME만 안다."""
    return dict(env) if env is not None else {"HOME": os.path.expanduser("~")}


def walk(command, cwd, env):
    """조각마다 (펼친 조각, 걷은 토큰, GIT 경로 지정, 기준 자리, 뒤 구분자) — cd·pushd·지정 조각은 내지 않는다.
    기준 자리는 모르면 None. `cd -`는 앞 자리, 서브셸이 닫히면 열 때 자리로. env는 이 걷기에서 고친다."""
    out, base, prev, stack = [], cwd, None, []
    for part, sep in segments_with_seps(command):
        if part and part[0] in DECLARE:
            part = [t for t in part[1:] if "=" in t and not t.startswith("-")] or part  # export X=값 도 지정
        pairs = _assignments(part) if part else None
        if pairs:
            for name, value in pairs:
                value = _expand(value, env)
                env[name] = None if "$" in value or "`" in value else value
        elif part:
            part = [_expand(t, env) for t in part]
            tokens, env_paths = strip_prefix(part)
            if tokens and os.path.basename(tokens[0]) in ("cd", "pushd"):
                new = moved_base(tokens, base, prev)
                if new is not base:
                    prev, base = base, new
            elif tokens:
                out.append((part, tokens, env_paths, base, sep))
        if sep == "(":
            stack.append((base, prev))
        elif sep == ")" and stack:
            base, prev = stack.pop()
    return out


def strip_prefix(tokens):
    """앞의 변수 지정과 감싸는 명령을 걷는다. GIT_DIR·GIT_WORK_TREE 값은 경로로 돌려준다."""
    i, paths = 0, []
    while i < len(tokens):
        t = tokens[i]
        if "=" in t and not t.startswith("-") and t.split("=", 1)[0].isidentifier():
            if t.split("=", 1)[0] in GIT_PATH_ENV:
                paths.append(t.split("=", 1)[1])
            i += 1
        elif t in KEYWORDS:
            i += 1
        elif os.path.basename(t) == "uv" and tokens[i + 1:i + 2] == ["run"]:
            i += 2
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in UV_VALUE_OPTS else 1
        elif os.path.basename(t) in WRAPPERS:
            takes = WRAPPERS[os.path.basename(t)]
            wrapper = os.path.basename(t)
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in takes else 1
            if wrapper == "timeout" and i < len(tokens):
                i += 1
        else:
            break
    return tokens[i:], paths


TILDE_USER = re.compile(r"~([A-Za-z_][A-Za-z0-9._-]*)(?=/|$)")


def _expanduser(path):
    """`os.path.expanduser`에 더해, 이 맥에 없는 사용자 `~<이름>/…`는 내 홈의 부모(macOS `/Users`) 아래 `<이름>`으로 푼다
    (못 풀면 cwd 아래 엉뚱한 자리로 대조돼 판정이 꺼졌다). 있는 사용자는 `pwd`가 푼 그대로."""
    if path == "~+" or path.startswith("~+/"):  # 셸이 `$PWD`로 푼다 — 기준 자리 상대(`~-`는 앞 자리라 모름, README 못 보는 것)
        return "." + path[2:]
    out = os.path.expanduser(path)
    m = TILDE_USER.match(out) if out.startswith("~") else None
    if m is None:
        return out
    return os.path.dirname(os.path.expanduser("~")) + "/" + m.group(1) + out[m.end():]


def _anchored(path):
    """기준 자리 없이 풀리는 경로인가 — `/`·`~`로 시작(단 `~+`는 기준 자리 상대, · 동작 Minor 1)."""
    return path.startswith("/") or (path.startswith("~") and not (path == "~+" or path.startswith("~+/")))


def resolve(path, base):
    return os.path.realpath(os.path.join(base, _expanduser(path)))


def moved_base(tokens, base, prev=None):
    """cd·pushd 뒤 기준 자리. pushd는 경로 인자일 때만 옮기고, `-n`·`+N`·`-N`·인자 없음은 그대로 둔다.
    `cd -`는 앞 자리. 인자에 `$`·백틱이 남거나 모르는 자리에서 상대로 옮기면 None(모름). 그대로면 base 그 객체를 돌려준다."""
    name, args = os.path.basename(tokens[0]), tokens[1:]
    if name == "cd":
        while args and args[0] in ("-L", "-P", "-e", "-@", "-LP", "-PL", "--"):
            args = args[1:]  # 옵션 뒤 첫 맨 인자가 자리
        if not args:
            return os.path.expanduser("~")
        if args[0] == "-":
            return prev
        target = args[0]
    else:
        if "-n" in args or not args or args[0][:1] in "+-":
            return base
        target = args[0]
    if "$" in target or "`" in target or (base is None and not _anchored(target)):
        return None
    return resolve(target, base or "/")


def read_only(sub, rest):
    """리드 저장소에서 허용하는 읽기. config·remote·branch는 읽는 꼴만."""
    if sub in READS:
        return True
    if sub == "config":
        return bool({"--get", "--get-all", "--get-regexp", "--list", "-l"} & set(rest))
    if sub == "remote":
        return not rest or rest[0] in ("-v", "show", "get-url")
    if sub == "branch":
        return all(r.startswith("-") and r in ("--show-current", "-a", "-r", "-v", "-vv", "--list", "-l") for r in rest)
    return False


def under(path, lead):
    return path == lead or path.startswith(lead + os.sep)


def git_reason(args, lead, base, env_paths):
    paths, i = [resolve(p, base or "/") if base or _anchored(p) else None for p in env_paths], 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        flag, has_value = (a.split("=", 1)[0], "=" in a) if a.startswith("--") else (a[:2], len(a) > 2)
        value = None
        if flag in GIT_GLOBALS_WITH_VALUE:
            if has_value:
                value = a.split("=", 1)[1] if a.startswith("--") else a[2:]
                i += 1
            else:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 2
            if flag == "-c" and value.lower().startswith("alias."):
                return "git -c alias.*는 작업 세션에서 막혀 있다. 하위 명령을 그대로 쓴다."
            if flag == "--config-env" and "alias" in value.lower():
                return "git --config-env alias는 작업 세션에서 막혀 있다."
            if flag in GIT_PATH_FLAGS:
                anchor = paths[-1] if flag == "-C" and paths else base
                paths.append(resolve(value, anchor) if anchor or _anchored(value) else None)
        else:
            i += 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    if "$" in sub or "`" in sub:
        return "git 하위 명령 자리에 치환($·백틱)은 작업 세션에서 막혀 있다. 하위 명령을 그대로 쓴다."
    if sub in BLOCKED:
        return f"git {sub}은 작업 세션에서 막혀 있다. 되돌릴 일은 커밋으로 한다."
    if sub == "reset" and {"--hard", "--keep", "--merge"} & set(rest):
        return "git reset --hard/--keep/--merge는 작업 세션에서 막혀 있다. 되돌릴 일은 커밋으로 한다."
    if sub == "branch" and BRANCH_MOVES & set(rest):
        return "git branch 지우기·옮기기·덮어쓰기는 리드 일이다."
    target = None if None in paths else paths[-1] if paths else base  # 하나라도 모르면 모름
    if target is None and not read_only(sub, rest):
        return f"기준 자리를 몰라(셸 변수 cd 등) git {sub}이 리드 저장소를 가리키는지 볼 수 없다."
    if target is not None and under(target, lead) and not read_only(sub, rest):
        return f"리드 저장소({lead})에 git {sub}은 작업 세션이 하지 않는다. 읽기만 한다."
    return None


def reason(cmd, lead, cwd="/", depth=0, env=None):
    lead = os.path.realpath(lead)
    if PARAM_MANGLE.search(drop_heredoc_bodies(cmd)):
        return ("셸 매개변수 가공(${(…)…}·${x#…}·${x%…}·${x/…}·${x:a}·$x:u 꼴)은 셸 검사가 확인창을 띄워 세션이 멈춘다. "
                "여러 단계·반복·변수 가공이 있는 셸은 scratchpad에 스크립트 파일(bash 또는 python3)로 써서 돌린다.")
    if depth < 3:
        for inner in _unescaped_subs(drop_heredoc_bodies(cmd, quoted_only=True)):  # 따옴표 heredoc 본문은 글
            found = reason(inner, lead, cwd, depth + 1, env)
            if found:
                return found
    env = new_env(env)
    try:
        entries = walk(cmd, cwd, env)
    except ValueError:
        return "명령을 나눌 수 없다(닫히지 않은 따옴표 등). 고쳐서 다시 낸다."
    made = None
    for _, tokens, env_paths, base, _ in entries:
        name = os.path.basename(tokens[0])
        if name not in ("git", "eval") and _script_target(tokens):
            if made is None:
                made = _heredoc_scripts(entries, cmd)
            found = interp_git_reason(tokens, cmd, base, made) if name not in SHELLS and name not in SOURCES else None
            if not found and depth < 3:  # 셸 본문(heredoc·here-string·스크립트 파일·셸 shebang 실행 파일)의 git
                for body in _shell_bodies(tokens, cmd, base, made):
                    found = _body_git_reason(body, lead, base or cwd, depth + 1, env)
                    if found:
                        break
            if found:
                return found
        if name == "eval" and depth < 3:
            found = reason(" ".join(tokens[1:]), lead, base, depth + 1, env)
            if found:
                return found
        elif name in SHELLS and depth < 3:
            for j, t in enumerate(tokens[1:], 1):
                if t.startswith("-") and not t.startswith("--") and "c" in t[1:] and j + 1 < len(tokens):
                    found = reason(tokens[j + 1], lead, base, depth + 1, env)
                    if found:
                        return found
                    break
        elif name == "git":
            found = git_reason(tokens[1:], lead, base, env_paths)
            if found:
                return found
    return None


LAUNCHERS = {"caffeinate", "script"}  # 옵션 뒤 첫 낱말이 돌릴 명령(감싸기 목록 WRAPPERS 밖)
GIT_BLOCK_TAIL = "막힌 명령을 스크립트·인터프리터로 돌아가지 않는다 — 꼭 필요하면 리드에게 `[막힘]`으로."
FIND_RUNS = {"-exec", "-execdir", "-ok", "-okdir"}  # find가 뒤 낱말을 명령으로 돌리는 옵션


def _git_sub(args):
    """git 전역 옵션 뒤 하위 명령(없으면 None)."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        flag = a.split("=", 1)[0] if a.startswith("--") else a[:2]
        i += 2 if flag in GIT_GLOBALS_WITH_VALUE and not ("=" in a if a.startswith("--") else len(a) > 2) else 1
    return args[i] if i < len(args) else None


def _runner_tails(tokens):
    """실행기(`caffeinate`·`script` 옵션 뒤)가 돌리는 명령 꼬리 — 새 조각으로 다시 판정한다
    (`caffeinate zsh x.sh`의 x.sh 본문)."""
    out, names = [], [os.path.basename(t) for t in tokens]
    for k, name in enumerate(names):
        if name in LAUNCHERS:
            j = k + 1
            while j < len(tokens) and tokens[j].startswith("-"):
                j += 1
            if j < len(tokens):
                out.append(shlex.join(tokens[j:]))
    return out


def _shell_noexec(tokens):
    """셸 머리(`sh`·`bash`·`zsh` …)의 옵션에 `-n`·`-o noexec`(읽기만, 실행 않음 — 문법 검사)가 있나.
    첫 맨 낱말 앞 옵션만 본다. `-i`(대화형 셸은 `-n`을 무시)나 `+` 옵션(`+n`·`+o noexec`로 끔)이 있으면 아니다."""
    noexec, i = False, 1
    while i < len(tokens):
        t = tokens[i]
        if t.startswith("+"):
            return False
        if not t.startswith("-") or t in ("-", "--"):
            break
        if t.startswith("--"):
            i += 1
            continue
        if "i" in t[1:]:
            return False
        if "n" in t[1:]:
            noexec = True
        if t[-1] == "o" and i + 1 < len(tokens):  # `-o <이름>` — 값 낱말을 건넌다
            noexec = noexec or tokens[i + 1] == "noexec"
            i += 1
        elif "c" in t[1:]:
            break  # `-c <글>` — 뒤는 명령 글과 $0 …
        i += 1
    return noexec


def _find_runs(tokens):
    """find `-exec`·`-execdir`·`-ok`·`-okdir` 뒤 돌릴 명령 낱말들(`+` 앞까지 — `\\;`는 조각 나누기가 자른다)."""
    out = []
    for i, t in enumerate(tokens):
        if t in FIND_RUNS:
            sub = tokens[i + 1:]
            if "+" in sub:
                sub = sub[:sub.index("+")]
            if sub:
                out.append(sub)
    return out


def _git_arg_hit(args, sub, block_git_arg):
    """`<하위>:<인자>` 깃발에 걸린 인자(없으면 None). 하위 명령 뒤 낱말이 인자와 같거나 `<인자>=…`, 긴 옵션의 앞부분
    (`--` 뒤 한 글자 이상 — git은 모호하지 않은 줄임을 길이 제한 없이 받는다), 짧은 옵션 한 글자면 `-`로 묶인 무리 안. `--` 뒤(경로)는 보지 않는다. 옵션 값 자리는 가르지 않는다."""
    wanted = [a.split(":", 1)[1] for a in block_git_arg if a.split(":", 1)[0] == sub]
    if not wanted:
        return None
    for t in args:
        if t == "--":
            return None
        for arg in wanted:
            if t == arg or t.startswith(arg + "="):
                return arg
            if arg.startswith("--") and t.startswith("--") and len(t) >= 3 and "=" not in t and arg.startswith(t):
                return arg
            if len(arg) == 2 and arg[0] == "-" and arg[1] != "-" and t.startswith("-") and not t.startswith("--") and arg[1] in t[1:]:
                return arg
    return None


def gate_reason(cmd, cwd="/", block_git=(), depth=0, env=None, block_git_arg=()):
    """켜는 깃발 막음 — 셸 git 하위 명령(`block_git`)·하위 명령 인자(`block_git_arg`, `<하위>:<인자>`).
    깃발이 없으면 None. find `-exec` 류가 돌리는 명령도 새 조각으로 보고, 셸 `-n`(문법 검사만)의 본문은 보지 않는다.
    조각마다(`sh -c`·`eval`·`$( … )`·백틱 안, 따옴표 heredoc 본문은 글이라 뺌), 셸 본문(heredoc·스크립트 파일)도.
    인터프리터 본문의 git은 `reason`이 본다."""
    if not block_git and not block_git_arg:
        return None
    again = dict(block_git_arg=block_git_arg)
    if depth < 3:
        for inner in _unescaped_subs(drop_heredoc_bodies(cmd, quoted_only=True)):
            found = gate_reason(inner, cwd, block_git, depth + 1, env, **again)
            if found:
                return found
    env = new_env(env)
    try:
        entries = walk(cmd, cwd, env)
    except ValueError:
        return None  # 나눌 수 없는 명령은 reason이 막는다
    made = None
    for _, tokens, _, base, _ in entries:
        name = os.path.basename(tokens[0])
        if name == "git" and (block_git or block_git_arg):
            sub = _git_sub(tokens[1:])
            if sub in block_git:
                return f"[막힘] git {sub}은 이 작업 세션에서 막혀 있다 — 합치기·가지 다시 쓰기는 리드 몫이다. {GIT_BLOCK_TAIL}"
            rest = tokens[tokens.index(sub, 1) + 1:] if sub else []
            arg = _git_arg_hit(rest, sub, block_git_arg) if sub else None
            if arg:
                return (f"[막힘] git {sub} {arg}은 이 작업 세션에서 막혀 있다 — 제 브랜치 다시 쓰기는 리드 몫이다(새 커밋으로 고친다). "
                        f"{GIT_BLOCK_TAIL}")
        if depth >= 3:
            continue
        for tail in _runner_tails(tokens):  # 깃발 하나라도 켜지면 꼬리를 본다
            found = gate_reason(tail, base or cwd, block_git, depth + 1, env, **again)
            if found:
                return found
        # find 식이 `\;`로 끊겨 이어진 조각(`-exec … \; -exec …`, `\( … \)`)도 find로 본다
        if name == "find" or ((tokens[0].startswith("-") or tokens[0] in ("(", ")", "!")) and any(t in FIND_RUNS for t in tokens)):
            for run in _find_runs(tokens):
                found = gate_reason(shlex.join(run), base or cwd, block_git, depth + 1, env, **again)
                if found:
                    return found
            continue
        noexec = name in SHELLS and _shell_noexec(tokens)  # `bash -n` — 읽기만 하니 본문·-c 글을 보지 않는다
        if name == "eval":
            found = gate_reason(" ".join(tokens[1:]), base or cwd, block_git, depth + 1, env, **again)
            if found:
                return found
        elif noexec:
            continue
        elif name in SHELLS and any(t.startswith("-") and not t.startswith("--") and "c" in t[1:] for t in tokens[1:]):
            for j, t in enumerate(tokens[1:], 1):
                if t.startswith("-") and not t.startswith("--") and "c" in t[1:] and j + 1 < len(tokens):
                    found = gate_reason(tokens[j + 1], base or cwd, block_git, depth + 1, env, **again)
                    if found:
                        return found
                    break
        elif name != "git" and _script_target(tokens):
            if made is None:
                made = _heredoc_scripts(entries, cmd)
            for body in _shell_bodies(tokens, cmd, base, made):
                found = gate_reason(body, base or cwd, block_git, depth + 1, env, **again)
                if found:
                    return found
    return None


REDIRECT = re.compile(r"^\d*(?:<<<|<>|>>|<|>)&?")
GLOB_CHARS = set("*?[")
WORD_BREAKS = set(";&|()<>`")
DOTDOT = re.compile(r"(?:^|(?<=/))\.\.(?=/|$)")


def _span_end(text, i):
    """`${…}`·`$((…))`가 끝나는 자리(짝 괄호 다음). 짝이 없으면 글 끝."""
    opener, closer = ("{", "}") if text.startswith("${", i) else ("(", ")")
    depth, j = 0, i + 1
    while j < len(text):
        if text[j] == opener:
            depth += 1
        elif text[j] == closer:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(text)


def _shell_words(text):
    """따옴표·이스케이프를 따라 낱말을 가른다. [(입력 그대로의 낱말, [(글자, 셸이 펼칠 glob 글자인가)])].
    따옴표 안·`\\` 뒤 글자는 펼치지 않는다. 공백과 `;&|<>`·백틱에서 끊는다(`$(`의 안쪽도 낱말이 된다)."""
    words, raw, chars, quote, i = [], [], [], None, 0

    def flush():
        if raw:
            words.append(("".join(raw), list(chars)))
        raw.clear()
        chars.clear()

    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(text):
                raw.append(text[i:i + 2])
                chars.append((text[i + 1], False))
                i += 2
                continue
            raw.append(c)
            if c == quote:
                quote = None
            else:
                chars.append((c, False))
        elif c == "\\" and i + 1 < len(text):
            raw.append(text[i:i + 2])
            chars.append((text[i + 1], False))
            i += 1
        elif text.startswith("${", i) or text.startswith("$((", i):  # 매개변수 펼침·산술 안 `*`·`[`·`?`는 glob이 아니다
            end = _span_end(text, i)
            raw.append(text[i:end])
            chars.extend((ch, False) for ch in text[i:end])
            i = end
            continue
        elif c in "'\"":
            quote = c
            raw.append(c)
        elif c.isspace() or c in WORD_BREAKS:
            flush()
        else:
            raw.append(c)
            chars.append((c, c in GLOB_CHARS))
        i += 1
    flush()
    return words


def glob_dotdot_words(command):
    """glob 글자(`*`·`?`·`[`, 따옴표·`\\` 밖) 뒤에 `..` 마디가 오는 낱말들, 처음 나온 차례로.
    Claude Code는 이 꼴을 셸이 펼친 뒤에야 경로를 알 수 있어 bypass에서도 확인 창을 띄운다 — 훅이 먼저 거절한다.
    `..`이 glob 앞(`../*`)·마디가 아닌 것(`a*..b`·`{1..3}`)·따옴표 안 글롭·heredoc 본문·주석은 보지 않는다."""
    found = []
    for raw, chars in _shell_words(_drop_comments(drop_heredoc_bodies(command))):
        first = next((n for n, (_, glob) in enumerate(chars) if glob), None)
        if first is None:
            continue
        text = "".join(c for c, _ in chars)
        if any(m.start() > first for m in DOTDOT.finditer(text)) and raw not in found:
            found.append(raw)
    return found


# macOS(APFS)는 이름 대소문자를 가리지 않으니 경로·패턴을 접어 대조한다
CASE_FOLD = sys.platform == "darwin"


def _fold(text):
    return text.casefold() if CASE_FOLD else text


def _pattern_dir(pat):
    """패턴의 글롭 앞 디렉터리(글롭이 없으면 패턴 그대로)."""
    cut = min((pat.index(c) for c in GLOB_CHARS if c in pat), default=None)
    return pat if cut is None else (pat[:pat.rfind("/", 0, cut)] or "/")


def _real_pattern(pat):
    """글롭 앞 부분을 realpath한다(링크 루트·`..`)."""
    head = _pattern_dir(pat)
    return os.path.realpath(head) + pat[len(head):] if head != pat else os.path.realpath(pat)


def deny_patterns(deny_rules, home=None, bases=(), kinds=("Read",)):
    """`Read(경로)` 규칙만 (정규 경로, 아래 전부인지) 짝으로. //는 절대, ~/는 홈, 그 밖 /는 절대로 보고,
    상대 꼴은 bases(cwd·저장소 꼭대기)마다 붙인다. 끝 `/**`를 떼어 비면 `/`. kinds로 `Edit`·`Write`를 고른다."""
    out = []
    for rule in deny_rules or ():
        m = re.fullmatch(r"(\w+)\((.+)\)", rule.strip()) if isinstance(rule, str) else None
        if not m or m.group(1) not in kinds:
            continue
        pat = m.group(2)
        if pat.startswith("//"):
            pats = [pat[1:]]
        elif pat.startswith("~/"):
            pats = [os.path.join(home or os.path.expanduser("~"), pat[2:])]
        elif pat.startswith("/"):
            pats = [pat]
        else:
            pats = [os.path.join(b, pat) for b in bases if b]
        for one in pats:
            tree = one.endswith("/**")
            one = (one[:-3] if tree else one) or "/"
            pair = (_real_pattern(one), tree)
            if pair not in out:
                out.append(pair)
    return out


DOUBLE_STAR = re.compile(r"(?<=/)\*\*/")


def _glob_variants(pat):
    """`/**/` 자리마다 그대로 둔 것과 `**/`를 지운 것(사이 단계 0개)으로 펼친다."""
    out = [pat]
    for m in reversed(list(DOUBLE_STAR.finditer(pat))):
        out += [v[:m.start()] + v[m.end():] for v in out]
    return out


@functools.lru_cache(maxsize=512)
def _glob_regex(pat):
    """deny 글롭을 Claude Code 권한 꼴의 정규식으로: `*`·`?`·`[...]`는 `/`를 넘지 않고 `**`만 여러 단계.
    괄호 읽기는 fnmatch와 같다(`[!` 부정, 닫히지 않은 `[`는 글자). 정규식으로 못 바뀌면 None."""
    i, n, out = 0, len(pat), []
    while i < n:
        c = pat[i]
        i += 1
        if c == "*":
            if i < n and pat[i] == "*":
                while i < n and pat[i] == "*":
                    i += 1
                out.append(".*")
            else:
                out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i
            if j < n and pat[j] == "!":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 1
            if j >= n:
                out.append("\\[")
                continue
            stuff, i = pat[i:j], j + 1
            neg = stuff.startswith("!")
            stuff = re.sub(r"([\\\[\]&~|^])", r"\\\1", stuff[1:] if neg else stuff)
            out.append(f"[^/{stuff}]" if neg else f"(?!/)[{stuff}]")
        else:
            out.append(re.escape(c))
    try:
        return re.compile("".join(out), re.S)
    except re.error:
        return None


def _glob_match(path, pat):
    """deny 글롭 맞추기 한 자리. 정규식으로 못 바뀌는 패턴은 판정 예외 없이 글자 그대로 같을 때만(과 같은 뜻)."""
    rx = _glob_regex(pat)
    return path == pat if rx is None else rx.fullmatch(path) is not None


def _denied(path, patterns):
    fpath = _fold(path)
    for pat, tree in patterns:
        fpat = _fold(pat)
        if GLOB_CHARS & set(pat):
            for v in _glob_variants(fpat):
                if _glob_match(fpath, v) or (tree and _glob_match(fpath, v + "/**")):
                    return pat
        elif fpath == fpat or (tree and fpath.startswith(fpat.rstrip("/") + "/")):
            return pat
    return None


def repo_top_of(base):
    if base is None:
        return None
    d = base
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def _iglob(full):
    """글롭 펼침. 패턴이 정규식으로 못 바뀌면(3.9 fnmatch `[^-[` → re.error) 펼치지 않는다 — 그 낱말은 글자 그대로만
    후보다(판정 예외로 막지 않음)."""
    try:
        yield from glob.iglob(full)
    except re.error:
        return


def _candidates(tok, base, is_git, top):
    """토큰이 가리킬 수 있는 정규 경로들."""
    tok = REDIRECT.sub("", tok)
    raw = [tok]
    inner = re.search(r"\d*(?:<<<|<>|>>|<|>)&?(.+)$", tok)
    if inner:
        raw.append(inner.group(1))  # 낱말에 붙은 리다이렉션 `cat<파일`
    if "=" in tok:
        raw.append(tok.split("=", 1)[1])
    out = []
    for r in raw:
        if is_git and ":" in r and not r.startswith("-") and "://" not in r:
            found = _git_object_path(r)
            if found is not None:  # rev 쪽만 변수(`$c:<경로>`)여도 경로 쪽은 대조한다
                rel, top_relative = found
                root = top if top_relative else base if rel.startswith(("./", "../")) or not top else top
                if rel and "$" not in rel and "`" not in rel and (root is not None or rel.startswith("/")):
                    out.append(os.path.realpath(os.path.join(root or "/", rel)))
        if not r or "$" in r or "://" in r:
            continue
        if base is None and not _anchored(r):
            continue  # 기준 자리를 모르는 상대 경로는 보지 않는다(못 보는 것)
        full = os.path.join(base or "/", _expanduser(r))
        out.append(os.path.realpath(full))
        out.append(os.path.normpath(full))  # 링크 그대로의 자리도
        if GLOB_CHARS & set(r):
            out.extend(os.path.realpath(f) for f in _iglob(full))
    return out


STAGE = re.compile(r"^:[0-3]:")
PATHSPEC_MAGIC = re.compile(r"^:\(([^)]*)\)")


def _git_object_path(tok):
    """git 낱말의 `<rev>:<경로>`·`:<경로>`·`:N:<경로>`·pathspec 마법 `:/<경로>`·`:(top)<경로>`에서 (경로, 꼭대기 기준인가).
    `:N:`는 단계 번호를 걷고, `:/`·`:(top…)`은 꼭대기 기준, 그 밖 마법(`:(icase)` 등)은 `<rev>:<경로>`와 같이
    `./`·`../`가 아니면 꼭대기 기준으로 푼다(git은 cwd 기준 — 꼭대기로 보는 쪽이 과잉 쪽이라 둔다),
    빼기 마법(`:!`·`:^`·`:(exclude)`)은 읽는 경로가 아니라 None."""
    if tok.startswith(":/"):
        return tok[2:], True
    magic = PATHSPEC_MAGIC.match(tok)
    if magic:
        words = {w.strip() for w in magic.group(1).split(",")}
        if "exclude" in words:
            return None
        return tok[magic.end():], "top" in words
    if tok.startswith((":!", ":^")):
        return None
    if STAGE.match(tok):
        return tok[3:], False
    return tok.split(":", 1)[1], False


GIT_OBJECT_READERS = {"show", "cat-file", "archive", "ls-tree", "diff", "grep"}
DYNAMIC_PATH = re.compile(r"[$`]|\{\}")
GIT_PATHSPEC_READERS = {"show", "diff", "log", "whatchanged", "blame", "format-patch", "grep"}


def git_place(tokens, base):
    """`git …`의 (기준 자리, 하위 명령 자리). `-C <dir>`(여러 번이면 차례로, 붙인 `-C<dir>`도)을 따라가고, 값에 `$`·백틱이
    남거나 모르는 자리에서 상대로 옮기면 기준 자리는 None(경로 인자·`<rev>:./…`의 기준과 꼭대기를 정한다)."""
    i, where = 1, base
    while i < len(tokens) and tokens[i].startswith("-"):
        t = tokens[i]
        value = None
        if t == "-C" and i + 1 < len(tokens):
            value, i = tokens[i + 1], i + 2
        elif t.startswith("-C") and len(t) > 2:
            value, i = t[2:], i + 1
        elif t in GIT_GLOBALS_WITH_VALUE and "=" not in t:
            i += 2
            continue
        else:
            i += 1
            continue
        if "$" in value or "`" in value or (where is None and not _anchored(value)):
            where = None
        else:
            where = resolve(value, where or "/")
    return where, i


def _git_dynamic_hits(tokens):
    """객체 읽는 git 하위 명령의 `<rev>:<경로>`에서 경로 쪽을 셸이 실행 중에 정하면(변수·명령 치환·`xargs -I{}`) 대조할 수 없어
    막는다(`for f in $(git ls-tree …); do git show <rev>:$f`). deny가 있을 때만 부른다."""
    _, i = git_place(tokens, "/")
    if i >= len(tokens) or tokens[i] not in GIT_OBJECT_READERS | GIT_PATHSPEC_READERS:
        return []
    out, sub, rest = [], tokens[i], tokens[i + 1:]
    if sub == "grep":  # 찾을 무늬(`-e` 값, 없으면 첫 맨 인자)는 경로가 아니다
        values = {j + 1 for j, t in enumerate(rest) if t in ("-e", "-f", "--and", "--or", "--not")}
        if not values:
            values = {next((j for j, t in enumerate(rest) if not t.startswith("-")), -1)}
        rest = [t for j, t in enumerate(rest) if j not in values]
    if "--" in rest:  # `<rev> -- $f` — rev가 있을 때 pathspec을 셸이 실행 중에 정하면 막는다
        cut = rest.index("--")
        if any(not t.startswith("-") for t in rest[:cut]):
            for t in rest[cut + 1:]:
                if DYNAMIC_PATH.search(t):
                    out.extend(_blocked(f"git {sub} -- {t}", "경로를 셸이 실행 중에 정해(변수·명령 치환·xargs {}) deny와 대조할 수 없다 — "
                                        "경로를 글자로 한 줄씩 적는다"))
                    break
    if sub not in GIT_OBJECT_READERS:
        return out
    for t in rest:
        if t.startswith("-") or ":" not in t or "://" in t:
            continue
        found = _git_object_path(t)
        if found is not None and DYNAMIC_PATH.search(found[0]):
            out.extend(_blocked(f"git {tokens[i]} {t}", "경로를 셸이 실행 중에 정해(변수·명령 치환·xargs {}) deny와 대조할 수 없다 — "
                                "경로를 글자로 한 줄씩 적는다"))
    return out


QUIET = {"echo", "printf", "true", ":"}


def _quiet_loop(parts, i):
    """parts[i]가 `for … in …`이고 그 본문(`do`부터 `done`까지)이 읽지 않는 명령(echo·printf)뿐인가.
    본문이 무엇이든 읽으면 목록 낱말은 그 본문이 `$f`로 읽는 경로라 대조한다."""
    for part in parts[i + 1:]:
        words = [w.lstrip("$(`") for w in part]
        if words and words[0] == "do":
            words = words[1:]
        if not words:
            continue
        if words[0] == "done":
            return True
        if words[0] not in QUIET:
            return False
    return False


def _path_tokens(part, is_git, quiet_loop=False):
    """경로일 수 있는 토큰. 본문이 echo·printf뿐인 `for <이름> in <낱말…>` 조각은 낱말 목록이라 보지 않고
    (`$(for`·`` `for``도), git 밖에서 `:`로 시작하는 토큰(빌드 도구 작업 이름)도 경로가 아니다. git `rev:경로`는 모든 하위 명령에 그대로."""
    head = part[0].lstrip("$(`") if part else ""
    if head == "for" and "in" in part and quiet_loop:
        return []
    # 글롭 글자만인 낱말(`case … in *)`의 `*` 등)은 경로가 아니다
    return [t for t in part if (is_git or not t.startswith(":")) and set(t) - set("*?")]


UNKNOWN_BASE = "기준 자리를 몰라(셸 변수 cd 등) 볼 수 없다"
# 파일 이름 거르기 옵션 `--<옵션>=<글롭>`의 값은 경로가 아니다. 경로를 받는 옵션(`--file=`·
# `--exclude-from=`·`--ignore-file=` …)과 목록 밖 명령은 그대로 경로로 본다.
NAME_FILTER_CMDS = {"grep", "egrep", "fgrep", "rg", "fd", "rsync", "tar", "gtar", "bsdtar", "du", "diff"}
NAME_FILTER_OPT = re.compile(r"--(?:include|exclude|include-dir|exclude-dir|glob|iglob)=")


def _name_filter(name, tok):
    return name in NAME_FILTER_CMDS and NAME_FILTER_OPT.match(tok) is not None


def deny_read_hits(command, cwd, deny_rules, repo_top=None, depth=0, env=None):
    """명령의 토큰 가운데 deny `Read(…)`에 걸리는 것. 빈 목록이면 통과. 나눌 수 없는 명령은 빈 목록(reason이 막는다).
    cwd가 None이면 기준 자리를 모른다 — 상대 일반 토큰은 보지 않고, 상대 스크립트·경로 없는 재귀 읽기는 막는다."""
    patterns = deny_patterns(deny_rules, bases=(cwd, repo_top or repo_top_of(cwd)))
    if not patterns:
        return []
    env = new_env(env)
    before = dict(env)
    body = drop_heredoc_bodies(command)
    hits = []
    try:
        entries = walk(hide_subs(command), cwd, env)
    except ValueError:  # 리드 세션엔 reason이 걸려 있지 않아 여기서 막는다
        entries = None
    if depth < 3:  # `$( … )` 안은 걷기 앞 변수표와 같은 명령 지정을 안 뒤 변수표 둘로 본다
        for inner in _unescaped_subs(body):
            for table in (before, env):
                for hit in deny_read_hits(inner, cwd, deny_rules, repo_top, depth + 1, table):
                    if hit not in hits:
                        hits.append(hit)
    if entries is None:
        return hits + ["명령을 나눌 수 없다(닫히지 않은 따옴표 등) — 막음"]
    parts = [e[0] for e in entries]
    made = _heredoc_scripts(entries, command)
    for i, (part, tokens, _, base, sep) in enumerate(entries):
        name = os.path.basename(tokens[0])
        if depth < 3 and (name == "eval" or name in SHELLS):
            for t in tokens[1:]:
                if " " in t or ";" in t:
                    hits.extend(deny_read_hits(t, base, deny_rules, repo_top, depth + 1, env))
        top = repo_top or repo_top_of(base)
        if tokens[0].startswith("-"):
            pass  # find `\\;` 뒤 조각(print 등)은 명령이 아니다
        elif name == "find":
            hits.extend(_find_exec_hits(tokens, base, deny_rules, repo_top, depth))
            piped = sep == "|" and i + 1 < len(entries) and os.path.basename(entries[i + 1][0][0]) == "xargs"
            if piped or any(t in FIND_EXEC and i + 1 < len(tokens) and os.path.basename(tokens[i + 1]) not in QUIET
                            for i, t in enumerate(tokens)):
                hits.extend(_tree_hits(name, _find_roots(tokens), base, patterns))
        else:
            hits.extend(_entry_hits(tokens, command, base, deny_rules, repo_top, depth, patterns, top, made))
        path_base, path_top, after = base, top, 0
        if name == "git":
            grep_dir = _git_grep_dir(tokens)
            if grep_dir is not None:
                hits.extend(_tree_hits("git grep", [grep_dir], base, patterns))
            hits.extend(_git_dynamic_hits(tokens))
            path_base, after = git_place(tokens, base)
            if path_base is None and base is not None and any(not t.startswith("-") for t in tokens[after + 1:]):
                hits.extend(_blocked("git -C", UNKNOWN_BASE))
            elif path_base is None and tokens[after:after + 1] and tokens[after] in GIT_OBJECT_READERS:
                for t in tokens[after + 1:]:  # 꼭대기를 몰라 `<rev>:<상대 경로>`를 풀 수 없다
                    found = None if t.startswith("-") or ":" not in t or "://" in t else _git_object_path(t)
                    if found and found[0] and not found[0].startswith("/"):
                        hits.extend(_blocked(f"git {tokens[after]} {t}", UNKNOWN_BASE))
                        break
            if path_base is not base:
                path_top = repo_top or repo_top_of(path_base)
            if tokens[after:after + 1] == ["ls-tree"] and "--full-tree" in tokens[after:]:
                path_base = path_top  # 꼭대기 기준 경로
        recursive = _recursive(tokens)
        if recursive and name in ("grep", "egrep", "fgrep", "rg"):
            if base is None and not any(_anchored(t) for t in tokens[1:] if not t.startswith("-")):
                hits.extend(_blocked(name, UNKNOWN_BASE))
            elif base is not None and not any(
                    os.path.exists(os.path.join(base, _expanduser(t))) for t in tokens[1:] if not t.startswith("-")):
                pat = _covers(base, patterns)  # 경로 인자가 없으면 cwd를 통째로 읽는다
                if pat:
                    hits.append(f"{name} → {base} (deny Read({pat}) — 아래에 deny 경로가 든다)")
        dests = _receive_side(tokens) if recursive else set()
        own = _path_tokens(part, name == "git", _quiet_loop(parts, i))
        if name == "git":  # `-C` 뒤 하위 명령의 경로 인자는 `-C` 자리 기준, 앞 전역 옵션 값은 원래 자리 기준
            own = [(t, base, top) for t in own if t not in tokens[after:]] + [(t, path_base, path_top) for t in own if t in tokens[after:]]
        else:
            own = [(t, base, top) for t in own]
        for tok, tok_base, tok_top in own:
            if _name_filter(name, tok):
                continue
            words = _brace_expand(tok)
            if words is None:
                hits.extend(_blocked(tok, "중괄호 펼침이 너무 크다"))
                continue
            for path in (c for w in words for c in _candidates(w, tok_base, name == "git", tok_top)):
                pat = _denied(path, patterns) or (recursive and tok != tokens[0] and tok not in dests and _covers(path, patterns))
                if pat:
                    hits.append(f"{tok} → {path} (deny Read({pat}){' — 아래에 deny 경로가 든다' if recursive else ''})")
                    break
    return hits


FIND_LEAD_OPTS = {"-H", "-L", "-P", "-E", "-X", "-s", "-x", "-d"}


def _find_roots(tokens):
    """find의 뿌리 인자(앞 옵션을 건넌 뒤 첫 `-`·`(`·`!` 앞 낱말과 BSD `-f <뿌리>`). 없으면 ["."]."""
    roots, i = [], 1
    while i < len(tokens) and tokens[i] in FIND_LEAD_OPTS | {"-f"}:
        if tokens[i] == "-f" and i + 1 < len(tokens):
            roots.append(tokens[i + 1])
            i += 1
        i += 1
    while i < len(tokens) and not tokens[i].startswith(("-", "(", "!")):
        roots.append(tokens[i])
        i += 1
    return roots or ["."]


def _git_grep_dir(tokens):
    """`git … grep`이면 훑는 저장소 자리(C 값, 없으면 "."), 아니면 None."""
    i, where = 1, "."
    while i < len(tokens) and tokens[i].startswith("-"):
        if tokens[i] == "-C" and i + 1 < len(tokens):
            where = os.path.join(where, tokens[i + 1]) if not _anchored(tokens[i + 1]) else tokens[i + 1]
            i += 2
        elif tokens[i] in GIT_GLOBALS_WITH_VALUE and "=" not in tokens[i]:
            i += 2
        else:
            i += 1
    return where if i < len(tokens) and tokens[i] == "grep" else None


def _tree_hits(label, dirs, base, patterns):
    """디렉터리째 읽는 자리마다 아래에 deny가 드나. 모르는 기준 자리의 상대 자리는 막는다."""
    hits = []
    for d in dirs:
        if "$" in d or "`" in d:
            continue
        if base is None and not _anchored(d):
            hits.extend(_blocked(label, UNKNOWN_BASE))
            continue
        path = resolve(d, base or "/")
        pat = _denied(path, patterns) or _covers(path, patterns)
        if pat:
            hits.append(f"{label} → {path} (deny Read({pat}) — 아래에 deny 경로가 든다)")
    return hits


RECURSIVE_ALWAYS = {"rg", "tar", "rsync"}
RECURSIVE_FLAG = {"grep", "egrep", "fgrep", "cp", "zip", "scp"}


def _recursive(tokens):
    """디렉터리를 통째로 읽는 명령인가. 목록 밖 명령은 보지 않는다(docstring "못 보는 것")."""
    name = os.path.basename(tokens[0])
    if name in RECURSIVE_ALWAYS:
        return True
    if name not in RECURSIVE_FLAG:
        return False
    letters = set("rRa" if name == "cp" else "rR")
    return any(t == "--recursive" or (t.startswith("-") and not t.startswith("--") and letters & set(t[1:]))
               for t in tokens[1:])


def _tar_extract(args):
    """tar 풀기인가: `--extract`·`--get`, 첫 인자 옛 꼴(`xf`), 짧은 옵션 묶음의 x(`--exclude=…`는 아님)."""
    if "--extract" in args or "--get" in args:
        return True
    if args and not args[0].startswith("-") and "x" in args[0]:
        return True
    return any(a.startswith("-") and not a.startswith("--") and "x" in a[1:] for a in args)


def _receive_side(tokens):
    """재귀 명령의 받는 자리(cp·rsync·scp 끝 인자, tar 풀기 -C) — 읽지 않으니 재귀 대조에서 뺀다."""
    name, args = os.path.basename(tokens[0]), tokens[1:]
    if name in ("cp", "rsync", "scp"):
        target = _target_dir(name, args)
        if target:
            return {target}  # -t면 끝 인자는 원본이다
        plain = _args(name, args)
        return {plain[-1]} if len(plain) >= 2 else set()
    if name == "tar" and _tar_extract(args):
        value = _opt_value(args, ("-C", "--directory"))
        return {value} if value else set()
    return set()


def _inside(path, top):
    return path == top or path.startswith(top.rstrip("/") + "/")


def _covers(d, patterns):
    """d가 None(모름)이면 None.
    디렉터리 d 아래에 deny 패턴이 닿을 수 있으면 그 패턴: 패턴 글롭 앞 디렉터리가 d 아래이거나, d가 아래 전부
    패턴 안이거나, d가 `**` 패턴 글롭 앞 디렉터리 아래이고 d 아래에 그 패턴에 맞는 파일이 실제로 있을 때."""
    if d is None or not os.path.isdir(d):
        return None
    fd = _fold(d)
    for pat, tree in patterns:
        head = _pattern_dir(pat)
        fhead = _fold(head)
        if _inside(fhead, fd):
            return pat
        if tree and _inside(fd, fhead) and (head == pat or "**" in pat or _glob_prefix_matches(fd, _fold(pat))):
            return pat  # 글롭 패턴은 d 깊이까지 자른 앞부분에 d가 맞을 때만 아래에 든다
        if "**" in pat and _inside(fd, fhead) and _walk_hits(d, pat, tree):
            return pat
    return None


def _glob_prefix_matches(fd, fpat):
    """d가 패턴을 d 깊이까지 자른 앞부분에 맞나(`/T/*/.agents/rules`는 `/T/x`를 덮고 `/T/x/tmp`는 덮지 않음)."""
    parts, pparts = fd.rstrip("/").split("/"), fpat.rstrip("/").split("/")
    if len(parts) > len(pparts):
        return False
    return _glob_match("/".join(parts), "/".join(pparts[:len(parts)]))


WALK_LIMIT = 20000
# `**/<이름>` 꼬리는 이름만 견주는 빠른 길 — 이 저장소 9천 개 0.17초, 20만 ≈ 4초로 훅 제한 20초 안
WALK_LIMIT_NAME = 200000


def _walk_hits(d, pat, tree):
    """d 아래 파일 가운데 패턴에 맞는 것이 있나. 상한을 넘게 훑어야 하면 볼 수 없으니 막는다(훅 시간 제한)."""
    tail = pat.rsplit("/", 1)[-1]
    name_only = "/**/" in pat and not (GLOB_CHARS & set(tail))
    limit, ftail, seen = (WALK_LIMIT_NAME if name_only else WALK_LIMIT), _fold(tail), 0
    for top, dirs, files in os.walk(d):
        for name in files + dirs:
            seen += 1
            if seen > limit:
                return True
            if name_only and _fold(name) != ftail:
                continue
            if _denied(os.path.join(top, name), [(pat, tree)]):
                return True
    return False


BRACE_LIMIT = 256
BRACE_RANGE = re.compile(r"(-?\d+)\.\.(-?\d+)|([A-Za-z])\.\.([A-Za-z])")


def _brace_parts(inner):
    """중괄호 안을 펼칠 낱말들로. 펼치지 않는 꼴(쉼표·범위 없음)이면 None."""
    parts, depth, cur = [], 0, ""
    for c in inner:
        if c == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        depth += (c == "{") - (c == "}")
        cur += c
    if parts:
        return parts + [cur]
    m = BRACE_RANGE.fullmatch(inner)
    if not m:
        return None
    if m.group(1) is not None:
        a, b = int(m.group(1)), int(m.group(2))
        if abs(b - a) >= BRACE_LIMIT:
            return [""] * (BRACE_LIMIT + 1)
        step = 1 if b >= a else -1
        return [str(n) for n in range(a, b + step, step)]
    a, b = ord(m.group(3)), ord(m.group(4))
    step = 1 if b >= a else -1
    return [chr(n) for n in range(a, b + step, step)]


def _first_brace(tok):
    """펼칠 첫 중괄호 (시작, 끝, 낱말들). `${…}`·짝 없는 `{`·쉼표 없는 `{x}`는 건너뛴다."""
    for i, c in enumerate(tok):
        if c != "{" or (i and tok[i - 1] == "$"):
            continue
        depth = 0
        for j in range(i, len(tok)):
            depth += (tok[j] == "{") - (tok[j] == "}")
            if depth == 0:
                parts = _brace_parts(tok[i + 1:j])
                if parts is not None:
                    return i, j, parts
                break
    return None


def _brace_expand(tok):
    """셸 중괄호 펼침(쉼표 목록·`{a..b}`, 중첩). 낱말이 BRACE_LIMIT를 넘으면 None."""
    done, todo = [], [tok]
    while todo:
        word = todo.pop(0)
        found = _first_brace(word)
        if not found:
            done.append(word)
        else:
            i, j, parts = found
            todo.extend(word[:i] + x + word[j + 1:] for x in parts)
        if len(done) + len(todo) > BRACE_LIMIT:
            return None
    return done


INTERP = re.compile(r"^(?:python(?:\d+(?:\.\d+)?)?|node|perl|ruby|php|bun|deno|lua|Rscript)$")
AWKS = {"awk", "gawk", "mawk", "nawk"}
PY_VALUE_OPTS = {"-W", "-X"}  # python -I는 격리 플래그다
INTERP_VALUE_OPTS = {"-W", "-X", "-r", "--require", "-I", "-M"}
SHELL_VALUE_OPTS = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
SOURCES = {"source", "."}
# 버전·도움말 옵션. `-v`는 셸·python에서 자세히 찍기(표준 입력을 계속 읽음)라 넣지 않는다.
SHELL_INFO_OPTS = {"--version", "--help"}
INTERP_INFO_OPTS = {"--version", "--help", "-V", "-h"}
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}


def heredocs(cmd):
    """(heredoc 본문, 끝말이 따옴표로 감싸였나) 짝들(drop_heredoc_bodies가 걷는 줄). 따옴표 없으면 바깥 셸이 본문의
    `$`·백틱을 펼친다."""
    found, waiting, cur = [], [], []
    for line in cmd.split("\n"):
        if waiting:
            dash, word, quoted = waiting[0]
            if (line.lstrip("\t") if dash else line) == word:
                waiting.pop(0)
                found.append(("\n".join(cur), quoted))
                cur = []
            else:
                cur.append(line)
            continue
        waiting = [(m.group(1) == "-", m.group(3), bool(m.group(2))) for m in HEREDOC.finditer(line)]
    return found


def heredoc_bodies(cmd):
    """heredoc 본문들."""
    return [body for body, _ in heredocs(cmd)]


PY_INLINE = re.compile(r"-[bBdEiIOPqRsSuvx]*c(.*)", re.S)  # `-Ic`·`-c<코드>`(W·X는 값을 받아 빠짐)
# `-ne`·`-le`·`-e<코드>`: 첫 e·E 뒤는 코드. 앞 글자는 값을 붙여 받지 않는 깃발만(i·-I·-M·-F 등의 값에 든 e는 코드가 아님)
PERL_INLINE = re.compile(r"-[0-9adlnpsTtuUvwWX]*[eE](.*)", re.S)
NODE_INLINE = {"-e", "--eval", "-p", "--print", "-pe"}


def _inline_code(name, args, i):
    """args[i]가 인라인 코드 옵션이면 (코드) — 코드 낱말이 없으면 (None). 아니면 None."""
    t, nxt = args[i], (args[i + 1] if i + 1 < len(args) else None)
    if t in ("-c", "-e"):
        return (nxt,)
    if name.startswith("python"):
        m = PY_INLINE.fullmatch(t)
        return (m.group(1) or nxt,) if m else None
    if name in ("perl", "ruby"):
        m = PERL_INLINE.fullmatch(t)
        return (m.group(1) or nxt,) if m else None
    if name in ("node", "bun", "deno"):
        if t in NODE_INLINE:
            return (nxt,)
        if t.startswith(("--eval=", "--print=")):
            return (t.split("=", 1)[1],)
    return None


def _script_target(tokens):
    """(kind, target): kind는 shell·interp·exec·stdin-shell·stdin-interp, inline은 (inline, 문자열). 진입점이 아니면 None."""
    name = os.path.basename(tokens[0])
    args = tokens[1:]
    if name in SOURCES:
        return ("shell", args[0]) if args else None
    if name in AWKS:
        return ("interp", args[args.index("-f") + 1]) if "-f" in args[:-1] else None  # 인라인 awk는 못 보는 것
    shell = name in SHELLS
    if name in ("deno", "bun") and args[:1] == ["run"]:
        args = args[1:]
    if not shell and not INTERP.match(name):
        return ("exec", tokens[0]) if "/" in tokens[0] else None
    i, dash = 0, False
    while i < len(args):
        t = args[i]
        if "<<<" in t:
            word = t.split("<<<", 1)[1] or (args[i + 1] if i + 1 < len(args) else "")
            return ("herestring-shell" if shell else "herestring-interp", word)
        if "<<" in t and t.startswith("-"):
            return ("heredoc-shell" if shell else "heredoc-interp", None)
        if t == "<" and i + 1 < len(args):
            return ("shell" if shell else "interp", args[i + 1])
        if t.startswith("<<"):
            return ("heredoc-shell" if shell else "heredoc-interp", None)
        if t.startswith("<"):
            return ("shell" if shell else "interp", t[1:])
        if t.startswith(">") or t[:1].isdigit() and ">" in t:
            i += 2 if t in (">", ">>", "2>", "1>") else 1
            continue
        if t in (SHELL_INFO_OPTS if shell else INTERP_INFO_OPTS):
            return None  # 버전·도움말만 찍고 스크립트를 읽지 않는다
        if shell and t.startswith("-") and "c" in t[1:] and not t.startswith("--"):
            return None  # -c 인라인은 위에서 본다
        code = None if shell else _inline_code(name, args, i)
        if code is not None:
            return ("inline", code[0]) if code[0] is not None else None
        if not shell and t == "-m":
            return None
        if t in (SHELL_VALUE_OPTS if shell else PY_VALUE_OPTS if name.startswith("python") else INTERP_VALUE_OPTS):
            i += 2
            continue
        if t.startswith(("-", "+")) and t != "-":
            i += 1
            continue
        if t == "-":
            dash = True
            i += 1  # 표준 입력 표시 — 뒤 리다이렉션이 본문을 준다
            continue
        if dash:
            i += 1  # `-` 뒤 낱말은 스크립트 인자다(`python3 - a <<E`)
            continue
        return ("shell" if shell else "interp", t)
    return ("stdin-shell" if shell else "stdin-interp", None)


def _blocked(target, why):
    return [f"{target} → {why} — 막음"]


CODE_TOKEN = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"|([(\[{])|([)\]}])")
# 파이썬 따옴표 셋 글자: 줄 단위 따옴표 판독이 `''`·조각으로 갈라 안의 `"…"`·괄호를 코드로 읽던 것을 글자 하나로
TRIPLE_SCAN = re.compile(r"('''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\")|'[^'\n]*'|\"[^\"\n]*\"|#[^\n]*")  # 1번 묶음만 따옴표 셋
TRIPLE_FILL = ""  # U+E002(사용 안 하는 글자 하나) — 가린 글과 원문의 자리가 같다


def _mask_triple(text):
    """따옴표 셋 글자마다 같은 길이의 한 줄 `'…'`(안은 채움 글자)로 — 자리는 그대로라 데이터 범위를 원문 판독에 그대로 쓴다.
    데이터 자리 셈에서만 쓴다 — 후보를 모으는 판독은 원문 그대로라 데이터 아닌 따옴표 셋 속 글자는 후보로 남는다."""
    if "'''" not in text and '"""' not in text:
        return text
    # 왼쪽부터 차례로 — 한 줄 글자·`#` 주석 안의 `'''`는 따옴표 셋 머리가 아니다
    return TRIPLE_SCAN.sub(lambda m: "'" + TRIPLE_FILL * (m.end() - m.start() - 2) + "'" if m.group(1) else m.group(0), text)


class DataSpans:
    """데이터 자리 [시작, 끝) 범위들(의 시작 자리 집합을 넓힘). `pos in spans`는 pos가 어느 범위 안에서 시작하는가."""

    def __init__(self, spans=()):
        self.spans = sorted(spans)
        self.starts = [a for a, _ in self.spans]

    def __contains__(self, pos):
        k = bisect.bisect_right(self.starts, pos) - 1
        return k >= 0 and pos < self.spans[k][1]

    def __bool__(self):
        return bool(self.spans)

    def __len__(self):
        return len(self.spans)

    def blank(self, text):
        """범위 안 글자를 빈칸으로 — 데이터 글자 안 따옴표 밖 낱말(따옴표 셋 속 낱말)을 후보에서 뺀다."""
        if not self.spans:
            return text
        out, pos = [], 0
        for a, b in self.spans:
            if a < pos:
                a = pos
            if a >= b:
                continue
            out += [text[pos:a], " " * (b - a)]
            pos = b
        out.append(text[pos:])
        return "".join(out)


# 문자열 고치기 호출: 값(고친 글)을 그대로 넘기는 감싸기처럼 건넌다. `.replace`는 두 인자 이상만(한 인자는 Path.replace — 쓰기),
# 받는 쪽이 `os`·`shutil`·`Path`·`pathlib`이거나 `os`를 다른 이름에 둔 것(`import os as o`·`o = os`)이면 아님(os.replace — 쓰기),
# 본문에 `__import__`·`import_module`·`from os import`가 있으면 아예 건너지 않는다. 받는 쪽 없는 이름
# (`from re import sub`)은 건너지 않고, 받는 쪽이 호출 결과(`)`)면 글자를 돌려주는 호출(`.read`·`.read_text`·`.decode` 등) 뒤일 때만.
EDIT_CALLS = {"replace", "sub", "subn"}
EDIT_NOT_RECV = {"os", "shutil", "Path", "pathlib"}
EDIT_AFTER = re.compile(r"\s*\.\s*(replace|sub|subn)\s*\(")
EDIT_OFF = re.compile(r"\b(?:__import__|import_module)\b|\bfrom\s+os\s+import\b")
OS_ALIAS = re.compile(r"\bimport\s+os\s+as\s+([A-Za-z_]\w*)|^[ \t]*([A-Za-z_]\w*)\s*=\s*os\s*(?:$|[;#])", re.M)
TEXT_RESULT = re.compile(r"\.\s*(?:read|read_text|decode|strip|rstrip|lstrip|lower|upper)\s*\(\s*\)\s*\.\s*(?:replace|sub|subn)\s*$")


@functools.lru_cache(maxsize=64)
def _edit_blocked_recv(text):
    """이 본문에서 고치기 호출로 건너지 않는 받는 쪽 이름들, 또는 None(건너기 끔)."""
    if EDIT_OFF.search(text):
        return None
    return frozenset(EDIT_NOT_RECV | {a or b for a, b in OS_ALIAS.findall(text)})


def _top_comma(text, i):
    """`(` 자리 i의 묶음에 깊이 0 쉼표가 있나(가린 본문 — 따옴표 글자는 CODE_TOKEN으로 건넌다)."""
    depth, pos = 0, i + 1
    for m in CODE_TOKEN.finditer(text, i + 1):
        if depth == 0 and "," in text[pos:m.start()]:
            return True
        if m.group(3):
            depth += 1
        elif m.group(4):
            if depth == 0:
                return False
            depth -= 1
        pos = m.end()
    return False


def _edit_call(entry, text):
    if entry[0] != "call" or entry[1] not in EDIT_CALLS or entry[2] is None or text is None:
        return False
    blocked = _edit_blocked_recv(text)
    if blocked is None or entry[2] in blocked:
        return False
    if entry[2] in (")", "]") and not TEXT_RESULT.search(text, max(0, entry[3] - 200), entry[3]):
        return False
    return entry[1] != "replace" or _top_comma(text, entry[3])


def _opaque(entry, text):
    """값을 그대로 넘기지 않는 호출(감싸기·고치기 호출 밖)."""
    return entry[0] == "call" and not _edit_call(entry, text)


CALLER = re.compile(r"(?:[A-Za-z_][\w.]*|[)\]])\s*$")
NOT_CALLERS = {"in", "not", "and", "or", "if", "elif", "while", "for", "return", "yield", "assert", "else", "lambda",
               "await", "is", "del", "import", "from", "with", "as", "print", "puts", "unless", "until", "when", "case"}
# ---- 본문 글자의 데이터 자리 ----
# 데이터 호출 인자이거나 데이터 자리에서만 쓰는 상수의 글자는 경로로 쓰이지 않는다 — 읽기·쓰기 후보에서 뺀다.
DATA_CALLS = {"print", "puts", "log", "info", "debug", "warning", "warn", "error", "dumps", "dump", "startswith",
              "endswith", "fail", "exit"}
DATA_METHODS = {"write", "writelines", "write_text", "write_bytes"}  # 받는 쪽이 있을 때만(파일 객체·Path의 내용 쓰기)
PATH_CLASSES = {"File", "IO", "Files", "Dir", "fs", "fsp", "Deno", "Bun"}  # 첫 인자가 경로인 클래스 — 그 write는 데이터 호출 아님
PASS_CALLS = {"any", "all", "sorted", "list", "tuple", "set", "len", "str", "repr"}  # 값을 그대로 넘김 — 그 바깥 호출로 가린다
DYNAMIC_NAMES = re.compile(r"\b(?:getattr|globals|vars|locals|__dict__|exec|eval)\b")  # 이름을 글자로 꺼냄 → 지정 빼기 안 함
ASSIGN = re.compile(r"(?:^|;)[ \t]*(?:(?:const|let|var|my|our|local)\s+)?\$?([A-Za-z_]\w*)[ \t]*=(?![=~])", re.M)  # 머리는 줄 머리와 `;` 뒤 — 줄 끝은 부르는 쪽이 센다
CALL_HEAD = re.compile(r"(?:([A-Za-z_]\w*|[)\]])\s*\.\s*)?([A-Za-z_]\w*)\s*$")
STRING_PREFIX = {"f", "r", "b", "u", "rb", "br", "fr", "rf"}
WORD_BEFORE = re.compile(r"([A-Za-z_]\w*)(\s*)$")
COMPREHENSION = re.compile(r"\b(?:for|lambda)\b")
ARCHIVE_RECV = re.compile(r"zip|tar|^[zt]f$", re.I)  # `zf.write('<경로>')`는 그 경로를 읽어 옮긴다 — 데이터 호출 아님
IDENT = re.compile(r"[A-Za-z_]\w*")
BARE_INTERP = re.compile(r"\s*(?:![rsa])?(?::[^{}]*)?\}")  # f-string 맨 이름 꽂기 `{NAME}`·`{NAME!r}`·`{NAME:>5}`


def _call_entry(text, i):
    """`(` 자리 i 앞 → ("call", 이름, 받는 쪽|None, i) 또는 ("grp")."""
    m = CALL_HEAD.search(text, max(0, i - 80), i)
    if not m or m.group(2) in NOT_CALLERS - {"print", "puts"}:
        return ("grp",)
    return ("call", m.group(2), m.group(1), i)


def _data_ctx(stack, text=None, pos=None):
    """가장 가까운 둘러싼 호출(괄호·대괄호·중괄호 묶음과 값을 그대로 넘기는 감싸기 호출은 건넘)이 데이터 호출인가.
    그 호출 `(`부터 pos까지에 `for`·`lambda`가 있으면(컴프리헨션·제너레이터·함수 — 안에서 경로를 열 수 있다) 아니다."""
    for entry in reversed(stack):
        if entry[0] == "call" and entry[1] not in PASS_CALLS and not _edit_call(entry, text):  # 고치기 호출도 건넘
            name, recv = entry[1], entry[2]
            data = (name in DATA_CALLS or name.startswith("assert")
                    or (name in DATA_METHODS and recv is not None and recv not in PATH_CLASSES
                        and not ARCHIVE_RECV.search(recv)))
            if data and text is not None and COMPREHENSION.search(text, entry[3], pos):
                return False
            return data
    return False


def _bare_arg(text, start):
    """글자 바로 앞이 이름 — 괄호 없는 호출의 인자(`File.read '<x>'`)면 참. 붙은 문자열 머리(`f'…'`)는 아님."""
    m = WORD_BEFORE.search(text, max(0, start - 80), start)
    return bool(m) and not (not m.group(2) and m.group(1).lower() in STRING_PREFIX)


def _code_tokens(text):
    """(CODE_TOKEN마다 (시작, 끝, 문자열인가, 앞 묶음, 뒤 묶음), 짝이 맞았나)."""
    out, stack, balanced = [], [], True
    for m in CODE_TOKEN.finditer(text):
        before = tuple(stack)
        if m.group(3):
            stack.append(_call_entry(text, m.start()) if m.group(3) == "(" else ("grp",))
        elif m.group(4):
            if stack:
                stack.pop()
            else:
                balanced = False
        out.append((m.start(), m.end(), not (m.group(3) or m.group(4)), before, tuple(stack)))
    return out, balanced and not stack


def _rhs_end(text, toks, k, start, line_end):
    """지정 오른쪽 끝 — start 뒤 따옴표 밖·묶음 깊이 0에서 처음 나오는 `;`, 없으면 줄 끝."""
    depth, pos = 0, start
    while k < len(toks) and toks[k][0] < line_end:
        t0, t1, is_str = toks[k][0], toks[k][1], toks[k][2]
        semi = text.find(";", pos, t0) if depth == 0 else -1
        if semi != -1:
            return semi
        if not is_str:
            depth += 1 if text[t0] in "([{" else -1 if depth else 0
        pos, k = t1, k + 1
    semi = text.find(";", pos, line_end) if depth == 0 else -1
    return semi if semi != -1 else line_end


def _data_starts(text):
    """데이터 자리 문자열의 시작 자리 집합: 데이터 호출의 (괄호 없는 안쪽 호출·컴프리헨션이 아닌) 인자, 또는 호출 밖
    `NAME = …`(첫 `;`까지)의 오른쪽 글자이고 NAME의 다른 모든 쓰임이 데이터 호출 안(문자열 안 쓰임은 맨 이름 꽂기 `{NAME}`일 때
    그 문자열 자리)이거나 다른 데이터 상수의 지정 오른쪽일 때. 묶음 짝이 안 맞으면(주석·깨진 문자열의 `(`) 빼지 않는다.
    : 따옴표 셋은 글자 하나로 가려 읽고(`_mask_triple`), 돌려주는 것은 [시작, 끝) 범위(`DataSpans`) — 원문 판독의
    글자가 범위 안에서 시작하면 데이터다. 문자열 고치기 호출(`EDIT_CALLS`)은 감싸기처럼 건너고, 지정 머리는 `;` 뒤도 센다."""
    src, text = text, _mask_triple(text)
    toks, balanced = _code_tokens(text)
    if not balanced:
        return DataSpans()
    strings = [t for t in toks if t[2]]
    data = {(t[0], t[1]) for t in strings if _data_ctx(t[3], text, t[0]) and not _bare_arg(text, t[0])}
    if DYNAMIC_NAMES.search(src):
        return DataSpans(data)
    starts = [t[0] for t in toks]

    def at(pos):
        k = bisect.bisect_right(starts, pos) - 1
        return toks[k] if k >= 0 else None

    lhs, spans = {}, []  # 이름 → [(이름 시작, 오른쪽 시작, 오른쪽 끝)], spans = 오른쪽 자리(시작 차례)
    for m in ASSIGN.finditer(text):
        t = at(m.start())
        if t is not None and t[2] and m.start() < t[1]:
            continue  # 따옴표 글자 안의 `; x = …`는 지정이 아니다
        k = bisect.bisect_left(starts, m.end(1))
        line_end = text.find("\n", m.end())
        end = _rhs_end(text, toks, k, m.end(1), len(text) if line_end == -1 else line_end)
        lhs.setdefault(m.group(1), []).append((m.start(1), m.end(1), end))
        spans.append((m.end(1), end, m.group(1)))
    if not lhs:
        return DataSpans(data)
    span_starts = [a for a, _, _ in spans]
    heads = {h for found in lhs.values() for h, _, _ in found}
    # 쓰임 색인 — 한 번 훑기(: 이름마다 본문 전체를 훑지 않게)
    users, plain_ok = {}, {n: True for n in lhs}  # users[A] = A를 오른쪽에 쓰는 지정 이름들
    for u in IDENT.finditer(src):  # 원문 — 따옴표 셋 f-string 안 쓰임도 본다(가린 글에서는 사라진다)
        name = u.group(0)
        if name not in lhs or u.start() in heads or (u.start() and src[u.start() - 1] in "\\.$"):
            continue
        t = at(u.start())
        inside = t is not None and t[2] and u.start() < t[1]
        if inside:
            if not BARE_INTERP.match(src, u.end()) or src[u.start() - 1:u.start()] != "{":
                plain_ok[name] = False  # f-string 식 안 이름(맨 이름 꽂기 아님)은 비데이터(Important 3)
                continue
            stack = t[3]
        else:
            stack = t[4] if t is not None else ()
        if _data_ctx(stack, text, u.start()):
            continue
        k = bisect.bisect_right(span_starts, u.start()) - 1
        owner = spans[k][2] if k >= 0 and u.start() < spans[k][1] and not any(_opaque(e, text) for e in stack) else None
        if owner == name and not inside and _self_edit(stack, text, u.end()):
            continue  # 자기 지정 오른쪽의 고치기 받는 쪽·인자(`s = s.replace(…)`·`s = re.sub(p, r, s)`) —
        if owner is None or owner == name:
            plain_ok[name] = False
        else:
            users.setdefault(name, set()).add(owner)
    # 고정점(일감 목록): 비데이터 쓰임이 있거나 비데이터 이름에 쓰인 이름은 비데이터
    used = set(users)
    for u in IDENT.finditer(src):  # 쓰임이 하나도 없는 상수는 데이터로 보지 않는다(옛 판 그대로 — 시험)
        if u.group(0) in lhs and u.start() not in heads:
            used.add(u.group(0))
    bad = {n for n, ok in plain_ok.items() if not ok or n not in used}
    rev = {}
    for n, owners in users.items():
        for o in owners:
            rev.setdefault(o, set()).add(n)
    work = list(bad)
    while work:
        o = work.pop()
        for n in rev.get(o, ()):
            if n not in bad:
                bad.add(n)
                work.append(n)
    for name, found in lhs.items():
        if name in bad:
            continue
        for _, a, b in found:
            for t in strings:
                if a < t[0] < b and not any(_opaque(e, text) for e in t[3]):
                    data.add((t[0], t[1]))
    return DataSpans(data)


def _self_edit(stack, text, end):
    """자기 지정 오른쪽 쓰임이 고치기 호출의 받는 쪽(바로 뒤 `.replace(`)이거나 고치기 호출 인자인가."""
    if any(_edit_call(e, text) for e in stack):
        return True
    m = EDIT_AFTER.match(text, end)
    return bool(m) and _edit_call(("call", m.group(1), "_", m.end() - 1), text)


def _code_strings(text):
    """본문의 따옴표 문자열마다 (글자, 호출 인자 자리인가). 호출 인자 자리 = 둘러싼 괄호 가운데 하나가 이름·`)`·`]` 바로 뒤
    `(`(`open('.env')`·`run(['cat', '.env'])`). `x in ('.env')`·`['.env']`·`{'.env': 1}`·`print('.env')`는 아니다."""
    out, stack = [], []
    for m in CODE_TOKEN.finditer(text):
        if m.group(3):
            head = CALLER.search(text, max(0, m.start() - 64), m.start()) if m.group(3) == "(" else None
            word = head.group(0).strip().rsplit(".", 1)[-1] if head else ""
            stack.append(bool(head) and word not in NOT_CALLERS)
        elif m.group(4):
            if stack:
                stack.pop()
        else:
            out.append((m.group(1) if m.group(1) is not None else m.group(2), any(stack), m.start()))
    return out


def _word_hits(text, base, patterns, top):
    """셸로 나눌 수 없는 인터프리터 본문: 경로 꼴 낱말만 후보로 대조한다.
    `/` 없는 문자열(`'.env'`)은 호출 인자 자리일 때만 — 목록·비교·사전 열쇠의 글자는 경로로 쓰이지 않는다."""
    hits = []
    quoted = r"'([^'\n]*)'|\"([^\"\n]*)\""
    data = _data_starts(text)  # 데이터 자리 글자는 경로가 아니다
    strings = [w for w, called, at in _code_strings(text) if at not in data and (called or "/" in w or w.startswith("~"))]
    bare = re.sub(quoted, " ", data.blank(text)).split()  # 데이터 범위 안 낱말도 뺀다
    # 경로 꼴만: 공백 없는 문자열, 문자열 밖 낱말은 `/`가 들거나 `.`·`~`로 시작하는 것
    words = [w for w in strings if not any(c.isspace() for c in w)] + [
        w for w in bare if "/" in w or w.startswith((".", "~"))]
    for tok in dict.fromkeys(words):
        if not tok or len(tok) > 4096:
            continue
        for path in _candidates(tok, base, False, top):
            pat = _denied(path, patterns)
            if pat:
                hits.append(f"{tok} → {path} (deny Read({pat}))")
                break
    return hits


def _body_hits(lang, label, text, base, deny_rules, repo_top, depth, patterns, top):
    if lang == "shell":
        try:
            list(segments(text))
        except ValueError:
            return _blocked(label, "본문을 나눌 수 없다")
        return deny_read_hits(text, base, deny_rules, repo_top, depth + 1)
    return _word_hits(text, base, patterns, top)


HEREDOC_TOKEN = re.compile(r"\d*<<(?!<)")
OUT_REDIRECT = re.compile(r"1?>>?(?!&)(.+)")


def _heredoc_scripts(entries, command):
    """같은 명령 안 `cat > f <<E`·`cat <<E >> f`·`tee f <<E`가 만드는 파일 → (heredoc 본문, 끝말 따옴표) .
    판정 때 아직 없는 스크립트(`… && python3 f`)를 그 본문으로 본다. 조각의 heredoc 수가 본문 수와 어긋나면 빈 dict(옛 길)."""
    found = heredocs(command)
    marks = [sum(1 for t in e[1] if HEREDOC_TOKEN.match(t)) for e in entries]
    if not found or sum(marks) != len(found):
        return {}
    made, k = {}, 0
    for (_, tokens, _, base, _), n in zip(entries, marks):
        name = os.path.basename(tokens[0])
        if n == 1 and base is not None and name in ("cat", "tee"):
            out, plain, args = None, [], tokens[1:]
            i = 0
            while i < len(args):
                t = args[i]
                m = OUT_REDIRECT.fullmatch(t)
                if t in (">", ">>", "1>", "1>>") and i + 1 < len(args):
                    out, i = args[i + 1], i + 2
                    continue
                if m:
                    out = m.group(1)
                elif t in ("<", "<<", "<<-", "2>", "2>>") or t[:1] and t[:1] in "<>" or re.match(r"\d+[<>]", t):
                    i += 2 if t in ("<", "<<", "<<-", "2>", "2>>") else 1  # 띄어 쓴 끝말 `<< 'E'`도 함께 건넘
                    continue
                elif not t.startswith("-"):
                    plain.append(t)
                i += 1
            target = out if name == "cat" and not plain else plain[0] if name == "tee" and len(plain) == 1 else None
            if target and "$" not in target and "`" not in target:
                made[resolve(target, base)] = found[k]
        k += n
    return made


def _script_hits(kind, target, base, deny_rules, repo_top, depth, patterns, top, made=None):
    """스크립트 파일 본문을 같은 판정으로 본다. 못 보면 막는다(fail-closed).
    없는 파일을 같은 명령 앞 조각이 heredoc으로 만들면 그 본문을 본다(made)."""
    if "$" in target or "`" in target or target == "{}":
        return _blocked(target, "셸 변수에 담은 경로라 본문을 볼 수 없다(같은 명령 안 `X=<경로>` 지정은 펼쳐 본다)")
    if base is None and not _anchored(target):
        # 실행 파일(./build.sh 등)은 모르는 자리에서 본문을 못 찾던 옛 길과 같이 넘긴다(못 보는 것)
        return [] if kind == "exec" else _blocked(target, UNKNOWN_BASE)
    path = resolve(target, base or "/")
    if kind == "exec" and not (os.path.isfile(path) and os.access(path, os.X_OK)):
        return []
    if depth >= 3:
        return _blocked(target, "중첩이 너무 깊어 본문을 볼 수 없다")
    if made and path in made and not os.path.exists(path):
        body, quoted = made[path]
        if kind != "shell" and not quoted and ("$" in body or "`" in body):
            return _blocked(target, "따옴표 없는 heredoc 본문을 바깥 셸이 펼쳐 볼 수 없다")
        return _body_hits("shell" if kind == "shell" else "interp", target, body, base, deny_rules, repo_top, depth,
                          patterns, top)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return _blocked(target, f"본문을 읽을 수 없다({type(e).__name__})")
    if b"\0" in data[:4096]:
        return []  # 이진 파일은 스크립트 본문이 아니다
    text = data.decode("utf-8", errors="replace")
    lang = kind
    if kind == "exec":
        first = text.split("\n", 1)[0]
        lang = "interp" if first.startswith("#!") and not any(
            os.path.basename(w) in SHELLS for w in first[2:].split()) else "shell"
    return _body_hits(lang, target, text, base, deny_rules, repo_top, depth, patterns, top)


def _single_quoted_herestrings(command):
    """`<<<` 뒤 낱말 전체가 작은따옴표 한 덩어리인 것들 — 바깥 셸이 펼치지 않는다."""
    return set(re.findall(r"<<<\s*'([^']*)'(?=[\s;&|)]|$)", command))


def _entry_hits(tokens, command, base, deny_rules, repo_top, depth, patterns, top, made=None):
    found = _script_target(tokens)
    if not found:
        return []
    kind, target = found
    if kind == "inline":
        return _word_hits(_unmask(target), base, patterns, top)  # perl `"<경로"`
    if kind.startswith("herestring"):
        if ("$" in target or "`" in target) and target not in _single_quoted_herestrings(command):
            return _blocked(tokens[0], "here-string 본문을 바깥 셸이 펼쳐 볼 수 없다")
        return _body_hits(kind.split("-", 1)[1], tokens[0], target, base, deny_rules, repo_top, depth, patterns, top)
    if kind.startswith("stdin"):
        return _blocked(tokens[0], "표준 입력 스크립트는 본문을 볼 수 없다")
    if kind.startswith("heredoc"):
        lang = kind.split("-", 1)[1]
        found = heredocs(command)  # 같은 조각에 `<<`가 있을 때만 온다
        bodies = [body for body, _ in found]
        if lang == "interp" and any(not quoted and ("$" in body or "`" in body) for body, quoted in found):
            return _blocked(tokens[0], "따옴표 없는 heredoc 본문을 바깥 셸이 펼쳐 볼 수 없다")
        if not bodies:
            return _blocked(tokens[0], "표준 입력 스크립트는 본문을 볼 수 없다")
        if depth >= 3:
            return _blocked(tokens[0], "중첩이 너무 깊어 본문을 볼 수 없다")
        hits = []
        for body in bodies:
            hits.extend(_body_hits(lang, tokens[0], body, base, deny_rules, repo_top, depth, patterns, top))
        return hits
    if kind == "exec" and ("$" in tokens[0] or "`" in tokens[0]):
        return []  # 동적 첫 토큰은 명령 이름이라 보지 않는다
    return _script_hits(kind, target, base, deny_rules, repo_top, depth, patterns, top, made)


def _find_exec_hits(tokens, base, deny_rules, repo_top, depth):
    r"""find -exec 뒤 명령(조각 끝이나 `+`까지 — segments가 `\;`에서 자른다)을 같은 판정으로."""
    hits = []
    for i, t in enumerate(tokens):
        if t in FIND_EXEC:
            sub = tokens[i + 1:]
            if "+" in sub:
                sub = sub[:sub.index("+")]
            if not sub:
                continue
            if depth >= 3:
                return _blocked(" ".join(sub), "중첩이 너무 깊어 본문을 볼 수 없다")
            hits.extend(deny_read_hits(shlex.join(sub), base, deny_rules, repo_top, depth + 1))
    return hits


# ---- Bash 쓰기 대상 ----
REDIRECT_OUT = re.compile(r"^(\d*|&)(>>|>\||>|<>)(&?)")
REDIRECT_IN_WORD = re.compile(r"(\d*|&)(>>|>|<>)(&?)")
REDIRECT_ANY = re.compile(r"(\d*|&)(>>|>\||>|<>|<<<|<)&?")
XARGS_WRITERS = None  # 아래 TOUCH_LIKE·IN_PLACE 뒤에 정한다
COPY_LIKE = {"cp", "mv", "install", "ln", "rsync", "scp"}
TOUCH_LIKE = {"touch", "rm", "rmdir", "mkdir", "truncate", "unlink", "shred", "chmod", "chown", "chgrp"}
IN_PLACE = {"sed", "gsed", "perl", "ruby"}
OUT_OPTS = {"sort": {"-o", "--output"}, "curl": {"-o", "--output"}, "wget": {"-O", "--output-document"}}
VALUE_OPTS = {"truncate": {"-s", "--size", "-r", "--reference"}, "install": {"-m", "-o", "-g", "--mode", "--owner", "--group"},
              "rsync": {"-e", "--rsh", "--exclude", "--include", "--filter", "-f"}, "cp": {"-S"}, "ln": {"-S"},
              "sed": {"-e", "-f", "--expression", "--file"}, "perl": {"-e", "-E", "-M", "-I"}, "ruby": {"-e", "-r", "-I"}}
XARGS_WRITERS = TOUCH_LIKE | IN_PLACE | {"mv"}  # 받은 경로 자체를 쓰는 명령
WRITERS = COPY_LIKE | TOUCH_LIKE | IN_PLACE | set(OUT_OPTS) | {"tee", "dd", "tar", "unzip"}
TARGET_DIR_CMDS = {"cp", "mv", "install", "ln"}


def _target_dir(name, args):
    """cp·mv·install·ln의 `-t <dir>`·`-rt <dir>`·`--target-directory=<dir>` 값(rsync·scp의 -t는 다른 뜻, ·I3)."""
    if name not in TARGET_DIR_CMDS:
        return None
    for i, a in enumerate(args):
        if a.startswith("--target-directory="):
            return a.split("=", 1)[1]
        if a == "--target-directory" or (a.startswith("-") and not a.startswith("--") and a.endswith("t")):
            return args[i + 1] if i + 1 < len(args) else None
        if a.startswith("-t") and len(a) > 2:
            return a[2:]
    return None


def _args(name, args):
    """옵션 값을 건넌 맨 인자들."""
    takes, out, i = VALUE_OPTS.get(name, set()), [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            out.extend(args[i + 1:])
            break
        if a.startswith("-") and a != "-":
            short_t = name in TARGET_DIR_CMDS and not a.startswith("--") and a.endswith("t")
            i += 2 if a in takes or short_t or (name in TARGET_DIR_CMDS and a == "--target-directory") else 1
            continue
        out.append(a)
        i += 1
    return out


def _opt_value(args, names):
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                return args[i + 1]
            if n.startswith("--") and a.startswith(n + "="):
                return a.split("=", 1)[1]
            if not n.startswith("--") and a.startswith(n) and len(a) > len(n) and a[len(n)] != "-":
                return a[len(n):]
    return None


def _letters(args, letter):
    return any(a.startswith("-") and not a.startswith("--") and letter in a[1:] for a in args)


def _write_targets(part, tokens, base=None):
    """(대상, 디렉터리째인가) 목록. 목록은 예시가 아니라 이 가드의 전부다(문서는 "등")."""
    out = []
    for i, tok in enumerate(part):
        m = REDIRECT_OUT.match(tok) or REDIRECT_IN_WORD.search(tok)  # 낱말에 붙은 꼴 `hi>파일`
        if not m:
            continue
        rest = tok[m.end():] or (part[i + 1] if i + 1 < len(part) else "")
        if m.group(3) and (rest.isdigit() or rest == "-"):
            continue  # >&2 · 2>&1 은 fd
        if rest:
            out.append((rest, False))
    name, args, skip = os.path.basename(tokens[0]), [], False
    for t in tokens[1:]:  # 리다이렉션과 띄어 쓴 그 대상은 인자가 아니다
        if skip:
            skip = False
        elif REDIRECT_ANY.fullmatch(t):
            skip = True
        elif not REDIRECT_ANY.match(t):
            args.append(t)
    plain = _args(name, args)
    if name == "tee":
        out += [(a, False) for a in plain]
    elif name == "install" and _letters(args, "d"):
        out += [(a, False) for a in plain]  # install -d는 맨 인자마다 디렉터리를 만든다
    elif name in COPY_LIKE:
        target = _target_dir(name, args)
        if target:
            out.append((target, False))
        elif len(plain) >= 2:
            out.append((plain[-1], name == "rsync" and any(a.startswith("--delete") for a in args)))
        dest = target or (plain[-1] if len(plain) >= 2 else None)
        if name == "cp" and dest and (_letters(args, "r") or _letters(args, "R") or _letters(args, "a")
                                      or "--recursive" in args or "--archive" in args):
            srcs = plain if target else plain[:-1]
            if base is not None or _anchored(dest):
                if os.path.isdir(resolve(dest, base or "/")):  # 있는 디렉터리면 그 아래 원본 이름 자리를 통째로
                    out += [(os.path.join(dest, os.path.basename(src.rstrip("/"))), True) for src in srcs]
                    if any(src.endswith("/") for src in srcs):
                        out.append((dest, True))  # BSD cp `src/`는 내용을 받는 자리에 바로 푼다
                else:
                    out.append((dest, True))
        if name == "mv":
            out += [(a, True) for a in (plain if target else plain[:-1])]
    elif name in TOUCH_LIKE:
        tree = name in ("rm", "chmod", "chown", "chgrp") and (_letters(args, "r") or _letters(args, "R") or "--recursive" in args)
        out += [(a, tree) for a in (plain[1:] if name in ("chmod", "chown", "chgrp") else plain)]
    elif name in IN_PLACE:
        if name in ("sed", "gsed"):
            inplace = any(a.startswith(("-i", "--in-place")) for a in args) or _letters([a for a in args if not a.startswith("-i")], "i")
        else:
            inplace = any(a.startswith("-") and not a.startswith("--") and "i" in a[1:].split(".")[0] for a in args)
        if inplace:
            files = [a for a in plain if a]
            has_script = _opt_value(args, ("-e", "-f", "--expression", "--file", "-E")) is not None
            out += [(a, False) for a in (files if has_script else files[1:])]
    elif name in OUT_OPTS:
        value = _opt_value(args, tuple(OUT_OPTS[name]))
        if value:
            out.append((value, False))
    elif name == "dd":
        out += [(a[3:], False) for a in args if a.startswith("of=")]
    elif name == "tar":
        if _tar_extract(args):
            out.append((_opt_value(args, ("-C", "--directory")) or ".", False))  # 받는 자리 자체만
    elif name == "unzip":
        out.append((_opt_value(args, ("-d",)) or ".", False))
    elif name == "find" and ("-delete" in args or any(
            t in FIND_EXEC and i + 1 < len(tokens) and os.path.basename(tokens[i + 1]) in WRITERS for i, t in enumerate(tokens))):
        out += [(r, True) for r in _find_roots(tokens)]  # -exec의 {}는 뿌리 아래 아무 파일이다
    return out


def deny_write_hits(command, cwd, deny_rules, repo_top=None, depth=0, env=None, script_files=True):
    """Bash 쓰기 대상 가운데 deny `Edit(…)`·`Write(…)`에 걸리는 것. 빈 목록이면 통과.
    셸 진입(`$`·백틱·sh -c·eval·셸 heredoc·here-string·셸 스크립트 파일·find -exec)은 다시 본다.
    기준 자리를 모르는 상대 대상은 막는다. script_files=False면 인터프리터 스크립트 파일 본문 글자를 보지 않는다."""
    patterns = deny_patterns(deny_rules, bases=(cwd, repo_top or repo_top_of(cwd)), kinds=("Edit", "Write"))
    if not patterns:
        return []
    env = new_env(env)
    hits = []
    if depth < 3:
        for inner in _unescaped_subs(drop_heredoc_bodies(command)):
            hits.extend(deny_write_hits(inner, cwd, deny_rules, repo_top, depth + 1, env, script_files))
    try:
        entries = walk(command, cwd, env)
    except ValueError:  # 리드 세션엔 reason이 걸려 있지 않아 여기서 막는다
        return hits + ["명령을 나눌 수 없다(닫히지 않은 따옴표 등) — 막음"]
    links = {}  # 같은 명령 안 `ln -s`로 만든 링크 → 대상
    made = _heredoc_scripts(entries, command)  # 같은 명령 안 heredoc으로 만든 스크립트
    for k, (part, tokens, env_paths, base, _) in enumerate(entries):
        name = os.path.basename(tokens[0])
        if depth < 3:
            for inner in _write_inner(tokens, command, base):
                hits.extend(deny_write_hits(inner, base, deny_rules, repo_top, depth + 1,
                                            env if name in ("eval",) or name in SHELLS else None, script_files))
        targets = _write_targets(part, tokens, base)
        hits.extend(_code_write_hits(tokens, command, base, patterns, deny_rules, repo_top, depth, made, script_files))
        if name == "git":
            trees = [t.split("=", 1)[1] for t in part[:len(part) - len(tokens)] if t.startswith("GIT_WORK_TREE=")]
            found = git_write_targets(tokens, base, repo_top, env_paths, trees)
            if found is None:
                hits.extend(_blocked("git", "쓰기 대상(패치)을 볼 수 없다"))
                continue
            gbase, found = found
            for target, tree in found:
                hits.extend(_target_hits(target, tree, gbase, patterns, links))
        if name in PATCH_NAMES:
            found = patch_write_targets(tokens, base, command)
            if found is None:
                hits.extend(_blocked("patch", "쓰기 대상(패치 입력)을 볼 수 없다 — 패치를 파일로 받아 `-i <파일>`로 낸다"))
            else:
                for target, tree in found[1]:
                    hits.extend(_target_hits(target, tree, found[0], patterns, links))
        if name == "ln" and (_letters([a for a in tokens[1:] if a.startswith("-")], "s") or "--symbolic" in tokens):
            plain = _args("ln", tokens[1:])
            if len(plain) >= 2 and base is not None or (len(plain) >= 2 and plain[-1].startswith("/")):
                link = os.path.normpath(os.path.join(base or "/", plain[-1]))
                links[link] = os.path.realpath(os.path.join(os.path.dirname(link), _expanduser(plain[0])))
        prev = entries[k - 1] if k else None
        wrappers = [os.path.basename(w) for w in part[:len(part) - len(tokens)]]
        if prev and prev[4] == "|" and os.path.basename(prev[1][0]) == "find" and "xargs" in wrappers and name in XARGS_WRITERS:
            targets += [(r, True) for r in _find_roots(prev[1])]  # find 뿌리 아래 아무 파일을 받아 쓴다
            base = prev[3] if base is None else base
        for target, tree in targets:
            hits.extend(_target_hits(target, tree, base, patterns, None if name == "ln" else links))
    return hits


def _target_hits(target, tree, base, patterns, links=None):
    """쓰기 대상 하나(중괄호·글롭 펼침까지)가 deny에 걸리나. 모르는 기준 자리의 상대 대상은 막는다."""
    if "$" in target or "`" in target:
        return []
    if base is None and not _anchored(target):
        return _blocked(target, UNKNOWN_BASE)
    words = _brace_expand(target)
    if words is None:
        return _blocked(target, "중괄호 펼침이 너무 크다")
    fulls = []
    for w in words:
        full = os.path.join(base or "/", _expanduser(w))
        fulls.append(full)
        if GLOB_CHARS & set(w):
            found = list(itertools.islice(_iglob(full), WALK_LIMIT + 1))  # 다 만들기 전에 끊는다
            if len(found) > WALK_LIMIT:
                return _blocked(target, "글롭 펼침이 너무 크다")
            fulls.extend(found)
    for link, dest in (links or {}).items():  # 링크를 거친 쓰기는 링크 대상으로도
        fulls += [dest + os.path.normpath(f)[len(link):] for f in list(fulls) if _inside(os.path.normpath(f), link)]
    for full in fulls:
        for path in dict.fromkeys((os.path.realpath(full), os.path.normpath(full))):  # 같으면 한 번만
            pat = _denied(path, patterns) or (tree and _covers(path, patterns))
            if pat:
                return [f"{target} → {path} (deny Edit/Write({pat}){' — 아래에 deny 경로가 든다' if tree else ''})"]
    return []


# ---- 인터프리터 본문 쓰기 ----
# 의도 낱말만으로는 막지 않는다 — 같은 본문에 deny 경로 글자가 있어야 막으니 목록을 넓게 둔다.
CODE_WRITE_OPEN = re.compile(
    r"\b(?:open\w*|fdopen|sysopen|new)\b[^;\n]*?,\s*(?:mode\s*=\s*|flags?\s*[:=]\s*)?"
    r"(?:(['\"])[rbtUs]*[wax+][rwabtxs+]*\1|['\"]\s*(?:\+[<>]|>>?|\|))"  # 쓰기 모드 글자 · perl `>`·`>>`·`+<`·`|`
    r"|\.open\s*\(\s*(?:mode\s*=\s*)?['\"][rbt]*[wax+]"  # Path.open('w')
    r"|\bflags?\s*[:=]\s*['\"][rbts]*[wax+]")
CODE_WRITE_CALL = re.compile(
    r"\b(?:write_text|write_bytes|writeFile\w*|appendFile\w*|createWriteStream|write\w*Sync|copyFile\w*|cpSync"
    r"|copy|copy2|copyfile|copytree|copymode|copystat|move|renames?|renameSync|remove|removedirs|unlink\w*|rmdir\w*"
    r"|rm|rmSync|rmtree|delete|mkdir\w*|makedirs|symlink\w*|hardlink_to|link|link_to|linkSync|truncate\w*|chmod\w*"
    r"|chown\w*|lchown|utimes?\w*|touch|syswrite|mkfifo|mknod|FileUtils|File::Copy|File::Path|remove_tree|make_path"
    r"|subprocess|child_process|system|exec\w*|spawn\w*|popen|Popen|check_call|check_output|getoutput|qx"
    r"|eval|compile|__import__|getattr|O_WRONLY|O_RDWR|O_CREAT|O_APPEND|O_TRUNC)\b"
    r"|\b(?:File|IO|Files|Dir|fs|fsp|Deno|Bun)\s*\.\s*(?:write\w*|append\w*|create\w*|output\w*|binwrite)\b"  # File.write·Bun.write
    r"|\bos\s*\.\s*replace\b|\.replace\s*\(\s*[^,()]*\)")  # 한 인자 replace는 Path.replace(문자열 replace는 두 인자)
# 변수에 담은 모드(`m='w'; open(p, m)`): 열기가 있으면 어디 있든 쓰기 모드 글자. 'a'·'x' 한 글자는 dict 열쇠와 겹쳐 인자 자리에서만 본다
CODE_OPENER = re.compile(r"\b(?:open\w*|fdopen|sysopen|new)\b")
CODE_MODE_ANY = re.compile(r"(['\"])(?:[rbt]*w[rbt+]*|[rwabtx]*\+[rwabtx+]*|[ax][bt]|[bt][ax]|>>?|\+[<>])\1")
# 디렉터리째 쓰기: 지우기·복사의 재귀형과, 자리 아래를 훑어 고르는 것(`Path('.').rglob(…)` 뒤 write_text — find -exec와 같음)
CODE_TREE = re.compile(r"\b(?:rmtree|copytree|removedirs|rm_r|rm_rf|remove_tree|rmSync|cp_r|recursive"
                       r"|rglob|glob|iglob|walk|scandir|listdir|readdir\w*|Find|find)\b")
CODE_QUOTED = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")
CODE_JOIN_GAP = re.compile(r"[\s)]*[,+/][\s,+/(]*(?:[\w.]*\(\s*)?")  # `', '`·`' + '`·`') / '`·`', Path('`
PERL_MODE_HEAD = re.compile(r"^\+?(?:>>|[<>|])\s*")
PATH_NAME_CHAR = re.compile(r"[\w.~-]")  # 경로 이름 글자
DOTDOT_ONLY = re.compile(r"\.\.(?:/\.\.)*/?")
# 경로 잇기 호출의 글자 아닌 첫 인자 뒤 자리(`join(HERE, "..")`의 `join(HERE, `·`Path(__dirname, `·`resolve(dirname(f), `)
# — 그 뒤 이어진 `..` 런은 cwd 기준이 아니다. 다른 호출의 둘째 인자(`copy(f, '..')`)는 cwd 기준이라 아니다
AFTER_DYNAMIC_ARG = re.compile(r"\b(?:join|joinpath|Path|PurePath|resolve)\s*\(\s*[A-Za-z_][\w.]*(?:\([^'\"()\n]*\))?\s*,\s*$")


def _dotdot_only(w):
    """`..` 마디만으로 된 낱말(`..`·`../..`·`../../`) — 본문 글자 속 `os.path.join(HERE, "..", "..")` 이어짐."""
    return bool(DOTDOT_ONLY.fullmatch(w))


def _root_only(w):
    """`/`로 시작하고 경로 이름 글자가 없는 낱말(`/`·`//`·`/**`) — 나누기·주석 조각이고, 경로라면 뿌리와 그 글롭뿐이다.
    상대 글롭(`*`·`*/*`·`**`)은 자리 아래를 가리키니 남긴다."""
    return w.startswith("/") and not PATH_NAME_CHAR.search(w)


def _code_write_intent(name, text):
    return bool(CODE_WRITE_OPEN.search(text) or CODE_WRITE_CALL.search(text)
                or (CODE_OPENER.search(text) and CODE_MODE_ANY.search(text))
                or (name in ("perl", "ruby") and "`" in text))


def _code_path_words(text, depth=0):
    """본문의 경로 글자 후보: 공백 없는 따옴표 문자열과 그 이어 붙임, 따옴표 밖 `/`·`.`·`~` 낱말.
    `/`로 시작하고 경로 이름 글자(글자·숫자·`.`·`_`·`-`·`~`)가 없는 낱말 — 나누기 `/`·`//`, 주석 `/**` — 은 뺀다."""
    data = _data_starts(text)  # 데이터 자리 글자(그 안 문자열 포함)는 뺀다
    found = [m for m in CODE_QUOTED.finditer(text) if m.start() not in data]
    strings = [m.group(1) if m.group(1) is not None else m.group(2) for m in found]
    words = [s for s in strings if not any(c.isspace() for c in s)]
    dynamic = set()  # 글자 아닌 인자 뒤에 이어진 `..`만 든 런의 낱말 — 다른 자리에 홀로 서면 남는다
    if depth < 2:
        for s in strings:  # 문자열 안 문자열(`exec("open('…','w')")`)
            if "'" in s or '"' in s:
                words += _code_path_words(s, depth + 1)
    run, lead, kept = [], False, set()
    for k, m in enumerate(found):
        if run and CODE_JOIN_GAP.fullmatch(text[found[k - 1].end():m.start()]):
            run.append(strings[k])
        else:
            run, lead = [strings[k]], bool(AFTER_DYNAMIC_ARG.search(text[max(0, m.start() - 200):m.start()]))
        joined = ["/".join(run), "".join(run)] if len(run) >= 2 else []
        words += joined
        # 런마다 판정: 동적 첫 인자 뒤 `..`만 든 런의 낱말만 빼고, 다른 런이 낸 같은 낱말은 남긴다
        (dynamic if lead and all(_dotdot_only(x) for x in run) else kept).update([strings[k]] + joined)
    dynamic -= kept
    bare = CODE_QUOTED.sub(" ", data.blank(text)).split()  # 데이터 범위 안 낱말도 뺀다
    words += [w for w in bare if "/" in w or w.startswith((".", "~"))]
    out = []
    for w in dict.fromkeys(words):
        w = PERL_MODE_HEAD.sub("", w)
        if w and len(w) <= 4096 and not any(c.isspace() for c in w) and not _root_only(w) and w not in dynamic:
            out.append(w)
    return out


def _code_bodies(tokens, command, found):
    """본문 목록과 못 본 까닭 목록: 인라인·here-string·heredoc(5). 스크립트 파일은 보지 않는다.
    found는 `_script_target(tokens)`."""
    name = os.path.basename(tokens[0])
    if not found or found[0] not in ("inline", "herestring-interp", "heredoc-interp", "stdin-interp"):
        return [], []
    kind, target = found
    if kind == "inline":
        return [_unmask(target)], []  # 따옴표 안 `<`·`>`는 walk가 바꿔 둔다
    if kind == "stdin-interp":
        return [], [f"{name} → 표준 입력 스크립트는 본문을 볼 수 없다"]
    if kind == "herestring-interp":
        if ("$" in target or "`" in target) and target not in _single_quoted_herestrings(command):
            return [], [f"{name} → here-string 본문을 바깥 셸이 펼쳐 볼 수 없다"]
        return [_unmask(target)], []
    pairs = heredocs(command)
    if any(not quoted and ("$" in body or "`" in body) for body, quoted in pairs):
        return [], [f"{name} → 따옴표 없는 heredoc 본문을 바깥 셸이 펼쳐 볼 수 없다"]
    if not pairs:
        return [], [f"{name} → 표준 입력 스크립트는 본문을 볼 수 없다"]
    return [_unmask(body) for body, _ in pairs], []


# 코드 안 자리 옮기기 — 글자 인자면 그 자리도 기준으로, 아니면(변수) 상대 경로를 볼 수 없다
CODE_CHDIR = re.compile(r"\bchdir\b\s*\(?\s*(?:(['\"])([^'\"\n]*)\1)?")
CODE_SHELL_OUT = re.compile(r"\b(?:system|popen|Popen|subprocess|child_process|exec\w*|spawn\w*|check_call|check_output"
                            r"|getoutput|getstatusoutput|run|call|qx)\b|`")


def _shell_string_hits(body, base, deny_rules, repo_top, depth, script_files=True):
    """코드가 셸에 넘기는 문자열(공백 든 따옴표 문자열)을 셸 쓰기 판정으로. 셸로 못 나누는 글은 셸 명령이 아니라 건넌다."""
    if depth >= 3 or not CODE_SHELL_OUT.search(body):
        return []
    hits = []
    for m in CODE_QUOTED.finditer(body):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        if not any(c.isspace() for c in s):
            continue
        try:
            list(segments(s))
        except ValueError:
            continue  # 셸로 못 나누는 글(`don't …`)은 셸 명령이 아니다
        hits += deny_write_hits(s, base, deny_rules, repo_top, depth + 1, script_files=script_files)
    return hits


def _code_args(tokens, code):
    """코드 뒤 셸 인자 가운데 경로 꼴(`sys.argv`·`process.argv`로 받을 수 있는 것)."""
    out, seen = [], False
    for t in tokens[1:]:
        if t == code or (code and t.endswith(code) and t.startswith("-")):
            seen = True
            continue
        if not t.startswith(("-", "<", ">")) and ("/" in t or t.startswith((".", "~"))) and (seen or code is None):
            out.append(t)
    return out


def _script_file_text(kind, target, base, own_top, made):
    """인터프리터 스크립트 파일 본문 — 볼 수 없으면 None(그 막음은 읽기 판정 몫). 믿는 공통 도구도 None.
    같은 명령 앞 조각이 heredoc으로 만드는 파일은 그 본문. 실행 파일은 셸 아닌 shebang일 때만."""
    if kind not in ("interp", "exec") or "$" in target or "`" in target or target == "{}":
        return None
    if base is None and not _anchored(target):
        return None
    path = resolve(target, base or "/")
    if made and path in made and not os.path.exists(path):
        return made[path][0] if kind == "interp" else None
    if kind == "exec" and not (os.path.isfile(path) and os.access(path, os.X_OK)):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    text = data.decode("utf-8", errors="replace")
    if kind == "exec":
        first = text.split("\n", 1)[0]
        if not first.startswith("#!") or any(os.path.basename(w) in SHELLS for w in first[2:].split()):
            return None
    return text


def _code_write_hits(tokens, command, base, patterns, deny_rules, repo_top, depth, made=None, script_files=True):
    """인터프리터 본문의 쓰기: 쓰기 의도가 있으면 경로 글자(본문·코드 뒤 셸 인자)를 셸 쓰기 대상과 같은
    `_target_hits`로 대조하고, 코드가 셸에 넘기는 문자열은 셸 쓰기 판정으로 본다. 스크립트 파일 본문은 데이터 자리 아닌 공백 없는 절대·`~` 따옴표 글자만 그 자리 그대로(대체)."""
    name = os.path.basename(tokens[0])
    entry = _script_target(tokens)
    bodies, unseen = _code_bodies(tokens, command, entry)
    hits = [f"{u} — 쓰기 판정, 막음(0361)" for u in unseen]
    code = entry[1] if entry and entry[0] == "inline" else None
    script = None
    files = []
    if entry and entry[0] in ("interp", "exec") and script_files:
        script = entry[1]
        own_top = repo_top or (repo_top_of(base) if base else None)
        text = _script_file_text(entry[0], script, base, own_top, made)
        if text is not None:
            files = [text]
    for body in files:  # 스크립트 파일 본문: 데이터 자리 아닌 공백 없는 따옴표 글자 가운데 절대·`~` 경로를 그 자리 그대로만
        if body and _code_write_intent(name, body):  # — 흐름 스크립트 과잉 0(할 일 3 잰 표). 문자열 안 낱말·상대·이어 붙인 경로는 안 봄
            data = _data_starts(body)
            for m in CODE_QUOTED.finditer(body):
                w = m.group(1) if m.group(1) is not None else m.group(2)
                if m.start() in data or any(c.isspace() for c in w) or not _anchored(w) or _root_only(w):
                    continue
                found = next(iter(_target_hits(w, False, base or "/", patterns)), None)
                if found:
                    hits.append(f"{name} 스크립트 파일 본문 쓰기: {found} — 시험 파일이면 `{name} -m unittest …`로 돈다(본문을 보지 않는다)")
                    break
    for body in bodies:
        if not body or not _code_write_intent(name, body):
            continue
        tree = bool(CODE_TREE.search(body))
        moves = [m.group(2) for m in CODE_CHDIR.finditer(body)]
        if None in moves:
            hits.extend(_blocked(name, "본문이 작업 자리를 글자 아닌 값으로 옮겨(chdir) 상대 쓰기 경로를 볼 수 없다"))
            continue
        bases = [base] + [resolve(d, base) for d in moves if base is not None or _anchored(d)]
        shell = _shell_string_hits(body, base, deny_rules, repo_top, depth, script_files)
        if shell:
            hits.extend(f"{name} 본문 셸 문자열: {h}" for h in shell)
            continue
        for w in _code_path_words(body) + _code_args(tokens, code):
            if base is None and not _anchored(w) and not ("/" in w or w.startswith(".")):
                continue  # 모르는 자리에서는 경로 꼴 상대 글자만 막는다('w'·'utf-8'은 경로가 아님)
            found = next((h for b in bases for h in _target_hits(w, tree, b, patterns)), None)
            if found:
                hits.append(f"{name} 본문 쓰기: {found}")
                break
    return hits


# ---- 인터프리터 본문의 git 쓰기 ----
# 셸 git은 git_reason이 본다. 인터프리터 본문(인라인·here-string·heredoc·스크립트 파일)은 글자 대조로 git 호출 꼴만 본다:
# ① 같은 묶음(괄호·대괄호) 안 `git` 글자 뒤 항목들(글자 아닌 항목은 자리만) ② 셸 문자열·백틱의 `git <하위>` ③ 하이픈 든 하위 명령 글자
# (`git` 글자가 본문에 있을 때, 묶음과 상관없이). 데이터 자리 글자는 뺀다. 셸보다 넓다 — 작업 세션이 인터프리터로 히스토리를 고칠 까닭이 없다.
INTERP_GIT_BLOCKED = BLOCKED | {"reset", "commit-tree", "cherry-pick", "rebase", "replace", "filter-branch", "filter-repo",
                                "fast-import", "symbolic-ref", "read-tree", "merge", "am"}
INTERP_GIT_HYPHENED = {s for s in INTERP_GIT_BLOCKED if "-" in s}
CODE_BACKTICK = re.compile(r"`([^`\n]+)`")
CODE_SHELL_SEPS = {";", "&&", "||", "|", "&"}


def _is_git(word):
    return word is not None and (word == "git" or word.endswith("/git"))


def _git_items_problem(items):
    """`git` 뒤 항목(글자, 글자 아닌 항목은 None)으로 막을 하위 명령 이름 또는 None. 하위 명령이 글자가 아니면 못 본다."""
    i = 0
    while i < len(items):
        w = items[i]
        if w is None:
            return None
        if w in GIT_GLOBALS_WITH_VALUE:
            value = items[i + 1] if i + 1 < len(items) else None
            if w in ("-c", "--config-env") and value is not None and "alias" in value.lower():
                return f"{w} {value}"
            i += 2
            continue
        if w.startswith("-c") and "alias" in w.lower():
            return w
        if w.startswith("-"):
            i += 1
            continue
        rest = [x for x in items[i + 1:] if x is not None]
        if w in INTERP_GIT_BLOCKED:
            return w
        if w == "branch" and BRANCH_MOVES & set(rest):
            return "branch " + next(x for x in rest if x in BRANCH_MOVES)
        return None
    return None


def _group_items(text, start):
    """묶음 안 `start`(따옴표 글자 끝) 뒤부터 묶음이 닫힐 때까지 쉼표로 가른 항목들 — 따옴표 글자 하나면 그 값, 아니면 None."""
    items, depth, cur, i, quote = [], 0, "", start, None
    while i < len(text):
        c = text[i]
        if quote:
            cur += c
            if c == "\\" and i + 1 < len(text):
                cur += text[i + 1]
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"":
            quote, cur = c, cur + c
        elif c in "([{":
            depth, cur = depth + 1, cur + c
        elif c in ")]}":
            if depth == 0:
                break
            depth, cur = depth - 1, cur + c
        elif c == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    items.append(cur)
    out = []
    for raw in items[1:] if items and not items[0].strip() else items:  # 첫 조각은 `git` 글자 뒤 쉼표 앞(빈 것)
        m = CODE_QUOTED.fullmatch(raw.strip())
        if raw.strip():
            out.append((m.group(1) if m.group(1) is not None else m.group(2)) if m else None)
    return out


def _shell_git_problem(text):
    """셸 문자열(`git reset --soft HEAD~1`)에서 막을 git 하위 명령 — 셸로 못 나누면 None. 붙여 쓴 연산자(`a&&git …`·`cd x;git …`)도 나눈다."""
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return None
    for k, w in enumerate(words):
        if _is_git(w):
            tail = []
            for x in words[k + 1:]:
                if x in CODE_SHELL_SEPS:
                    break
                tail.append(x)
            found = _git_items_problem(tail)
            if found:
                return found
    return None


def body_git_problem(body):
    """인터프리터 본문의 막을 git 쓰기 하위 명령 또는 None."""
    data = _data_starts(body)
    quoted = [(m.start(), m.end(), m.group(1) if m.group(1) is not None else m.group(2))
              for m in CODE_QUOTED.finditer(body) if m.start() not in data]
    has_git = False
    for start, end, word in quoted:
        if _is_git(word):
            has_git = True
            found = _git_items_problem(_group_items(body, end))
            if found:
                return found
        elif any(c.isspace() for c in word) and "git" in word:
            found = _shell_git_problem(word)
            if found:
                return found
    for m in CODE_BACKTICK.finditer(body):
        found = _shell_git_problem(m.group(1))
        if found:
            return found
    if has_git:
        for _, _, word in quoted:
            if word in INTERP_GIT_HYPHENED:
                return word
    return None


def _shell_bodies(tokens, command, base, made=None):
    """셸·source 진입 조각의 본문들(heredoc·here-string·스크립트 파일)과 셸 shebang(또는 shebang 없는) 실행 파일 본문. 못 보면 빈 목록 —
    읽기 판정(pre_tool)이 못 보는 본문을 따로 막는다. 이진·큰 파일은 보지 않는다."""
    entry = _script_target(tokens)
    if not entry:
        return []
    kind, target = entry
    if kind == "heredoc-shell":
        return [body for body, _ in heredocs(command)]
    if kind == "herestring-shell":
        return [_unmask(target)]
    if kind not in ("shell", "exec") or "$" in target or "`" in target or target == "{}":
        return []
    if base is None and not _anchored(target):
        return []
    path = resolve(target, base or "/")
    if made and path in made and not os.path.exists(path):
        return [made[path][0]] if kind == "shell" else []
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > 1_000_000:
            return []
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    if b"\0" in data[:4096]:
        return []
    text = data.decode("utf-8", errors="replace")
    if kind == "exec":
        first = text.split("\n", 1)[0]
        if first.startswith("#!") and not any(os.path.basename(w) in SHELLS for w in first[2:].split()):
            return []  # 셸 아닌 shebang은 인터프리터 본문 판정 몫
    return [text]


def _body_git_reason(body, lead, cwd, depth, env):
    """셸 본문의 git 막음만 본다 — 셸 가공·나눌 수 없음은 본문에서 막지 않는다(빌드 도구 감싸기 같은 큰 스크립트가 막히지 않게)."""
    try:
        entries = walk(body, cwd, new_env(env))
    except ValueError:
        return None
    for _, tokens, env_paths, base, _ in entries:
        name = os.path.basename(tokens[0])
        if name == "git":
            found = git_reason(tokens[1:], lead, base, env_paths)
        elif name in SHELLS and depth < 3:
            found = next((_body_git_reason(tokens[j + 1], lead, base or cwd, depth + 1, env)
                          for j, t in enumerate(tokens[1:], 1)
                          if t.startswith("-") and not t.startswith("--") and "c" in t[1:] and j + 1 < len(tokens)), None)
        else:
            found = None
        if found:
            return "[막힘] 셸 본문: " + found + " 막힌 명령을 스크립트로 돌아가지 않는다 — 꼭 필요하면 리드에게 `[막힘]`으로."
    return None


def interp_git_reason(tokens, command, base, made=None):
    """인터프리터 진입 조각(`_script_target`)의 본문에 git 쓰기 하위 명령이 있으면 막는 글. 못 보는 본문은 읽기·쓰기 판정 몫."""
    name = os.path.basename(tokens[0])
    entry = _script_target(tokens)
    if not entry:
        return None
    bodies, _ = _code_bodies(tokens, command, entry)
    if entry[0] in ("interp", "exec"):
        own_top = repo_top_of(base) if base else None
        text = _script_file_text(entry[0], entry[1], base, own_top, made)
        if text is not None:
            bodies = bodies + [text]
    for body in bodies:
        found = body and body_git_problem(body)
        if found:
            return (f"[막힘] {name} 본문의 git {found}은 작업 세션에서 막혀 있다. 막힌 명령을 스크립트·인터프리터로 돌아가지 않는다 — "
                    "되돌릴 일은 커밋으로 하고, 커밋 나누기·가지 옮기기는 리드에게 `[막힘]`으로 알린다. "
                    "시험 파일이면 `python3 -m unittest …`로 돈다(본문을 보지 않는다).")
    return None


GIT_NO_WRITE = {"apply":{"--check", "--stat", "--numstat", "--summary"}, "rm": {"-n", "--dry-run", "--cached"},
                "mv": {"-n", "--dry-run"}}  # 하위 명령별 — checkout-index -n은 있는 파일을 덮어쓴다
PATCH_LINES = re.compile(r"^(?:(?:\+\+\+|---) (\S+)|diff --git (\S+) (\S+)|(?:rename|copy) (?:from|to) (.+))$", re.M)


def _patch_paths(text, strip):
    """패치가 고치는 경로들. `---`·`+++`·`diff --git`은 앞 strip 단계를 떼고, rename·copy 줄은 그대로."""
    out = []
    for m in PATCH_LINES.finditer(text):
        if m.group(4):
            out.append(m.group(4).strip())
            continue
        for p in (m.group(1), m.group(2), m.group(3)):
            if p and p != "/dev/null":
                parts = p.split("/")
                if len(parts) > strip:
                    out.append("/".join(parts[strip:]))
    return out


def git_write_targets(tokens, base, top=None, env_paths=(), work_trees=()):
    """git 쓰기 하위 명령의 (기준 자리, [(대상, 디렉터리째인가)]). 볼 수 없으면 None(막음).
    mv·rm·checkout-index·apply만 본다 — merge 등 작업 트리 쓰기는 못 보는 것. `--work-tree`·GIT_WORK_TREE는 기준 자리를 바꾼다."""
    tree = None  # --work-tree·GIT_WORK_TREE 자리 — git apply 패치 경로의 뿌리
    for wt in env_paths:
        base = resolve(wt, base) if base is not None or _anchored(wt) else None
        tree = base if wt in work_trees else tree  # GIT_DIR 값은 뿌리가 아니다
    args, i = tokens[1:], 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        flag = a.split("=", 1)[0]
        if flag in ("-C", "--work-tree"):
            nxt = a.split("=", 1)[1] if "=" in a else (args[i + 1] if i + 1 < len(args) else "")
            base = resolve(nxt, base) if base is not None or _anchored(nxt) else None
            tree = base if flag == "--work-tree" else tree
            i += 1 if "=" in a else 2
        elif a in GIT_GLOBALS_WITH_VALUE and "=" not in a:
            i += 2
        else:
            i += 1
    if i >= len(args):
        return base, []
    sub, rest = args[i], args[i + 1:]
    if GIT_NO_WRITE.get(sub, set()) & set(rest) and "--apply" not in rest:
        return base, []
    plain = [a for a in rest if not a.startswith("-")]
    if sub == "mv":
        return base, ([(plain[-1], True)] + [(p, True) for p in plain[:-1]]) if len(plain) >= 2 else []
    if sub == "rm":
        return base, [(p, _letters(rest, "r")) for p in plain]
    if sub == "checkout-index":
        prefix = _opt_value(rest, ("--prefix",))
        if prefix is not None:
            return base, [(prefix + p, False) for p in plain] or [(prefix or ".", True)]
        return base, [(p, False) for p in plain]
    if sub == "apply":
        d = _opt_value(rest, ("--directory",))
        if d is not None:
            return base, [(d, True)]
        if not plain or base is None:
            return None
        strip_value = _opt_value(rest, ("-p",))
        if strip_value is not None and not strip_value.isdigit():
            return None
        strip = int(strip_value) if strip_value is not None else 1
        root = tree or repo_top_of(base) or top or base  # -C·cd로 옮긴 저장소 꼭대기 기준(옛 꼴은 훅 cwd 꼭대기 먼저)
        out = []
        for patch in plain:
            try:
                with open(resolve(patch, base), encoding="utf-8", errors="replace") as f:
                    found = _patch_paths(f.read(), strip)
            except OSError:
                return None
            if not found:
                return None  # 고칠 경로를 하나도 못 뽑으면 볼 수 없다
            out += [(os.path.join(root, p), False) for p in found]
        return base, out
    return base, []


PATCH_NAMES = {"patch", "gpatch"}
PATCH_VALUE_OPTS = {"-p", "-d", "-i", "-o", "-r", "-B", "-D", "-F", "-V", "-Y", "-z", "-g", "-x", "--strip", "--directory", "--input",
                    "--output", "--reject-file", "--prefix", "--ifdef", "--fuzz", "--version-control", "--basename-prefix",
                    "--suffix", "--get", "--quoting-style", "--read-only"}
PATCH_NO_WRITE = {"--dry-run", "-C", "--check", "--version", "-v", "--help"}  # -C·--check는 BSD patch의 dry-run
PATCH_INDEX = re.compile(r"^Index: (\S+)$", re.M)


def _patch_opts(args):
    """patch 인자 → ({옵션: 값}, 맨 인자들, 표준 입력 [(꼴, 값)]). 리다이렉션은 표준 입력(`<`·`<<`·`<<<`)만 모은다."""
    opts, plain, stdin, i = {}, [], [], 0
    while i < len(args):
        a = args[i]
        m = re.match(r"^(\d*)(<<<|<<-?|<>|<|>>|>\||>)(.*)$", a)
        if m:
            value = m.group(3) or (args[i + 1] if i + 1 < len(args) else "")
            i += 1 if m.group(3) else 2
            if m.group(1) in ("", "0") and m.group(2) in ("<", "<<", "<<-", "<<<"):
                stdin.append((m.group(2), value))
            continue
        if a == "--":
            plain.extend(args[i + 1:])
            break
        if a.startswith("--"):
            key, eq, value = a.partition("=")
            if eq:
                opts[key] = value
            elif key in PATCH_VALUE_OPTS:
                opts[key] = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            else:
                opts[key] = None
        elif a.startswith("-") and len(a) > 1:
            for j in range(1, len(a)):  # 묶음 짧은 옵션(`-Np1`·`-sp1`·`-Ni f`) — 값 옵션 글자 뒤는 값
                key = "-" + a[j]
                if key in PATCH_VALUE_OPTS:
                    if a[j + 1:]:
                        opts[key] = a[j + 1:]
                    else:
                        opts[key] = args[i + 1] if i + 1 < len(args) else ""
                        i += 1
                    break
                opts[key] = None
        else:
            plain.append(a)
        i += 1
    return opts, plain, stdin


def patch_write_targets(tokens, base, command):
    """patch·gpatch의 (기준 자리, [(대상, False)]). 볼 수 없으면 None(막음).
    `-d`는 다른 일보다 먼저 옮기니 -i·맨 인자·-o·-r 상대 경로도 그 자리 기준(GNU patch). 맨 인자 첫째(originalfile)가 있으면
    그 파일만 고친다. 없으면 패치 본문(i·둘째 맨 인자·`<`·heredoc·here-string)의 경로를 `-p`만큼 떼어 본다 — `-p`가 없으면
    GNU·BSD가 다르게 떼니 맨 이름과 통째 경로 둘. 파이프 입력·없는 파일·모르는 `-p`는 볼 수 없다."""
    opts, plain, stdin = _patch_opts(tokens[1:])
    if PATCH_NO_WRITE & set(opts):
        return base, []
    shell_base = base  # `<` 리다이렉션은 셸이 연다 — -d 앞 자리 기준
    d = opts.get("-d", opts.get("--directory"))
    if d is not None:
        if "$" in d or "`" in d or (base is None and not _anchored(d)):
            return None
        base = resolve(d, base or "/")
    extra = [v for k in ("-o", "--output", "-r", "--reject-file") for v in [opts.get(k)] if v and v != "-"]
    if plain:
        return base, [(p, False) for p in ([] if opts.get("-o") or opts.get("--output") else plain[:1]) + extra]
    strip_value = opts.get("-p", opts.get("--strip"))
    if strip_value is not None and not strip_value.isdigit():
        return None
    texts = []
    files = [(v, base) for v in (opts.get("-i"), opts.get("--input")) if v is not None]
    for kind, value in stdin:
        if kind.startswith("<<") and kind != "<<<":
            texts += heredoc_bodies(command)
        elif kind == "<<<":
            texts.append(value)
        else:
            files.append((value, shell_base))
    if not files and not texts:
        return None  # 파이프·터미널 입력 — 볼 수 없다
    for f, at in files:
        if "$" in f or "`" in f or (at is None and not _anchored(f)):
            return None
        try:
            with open(resolve(f, at or "/"), encoding="utf-8", errors="replace") as fh:
                texts.append(fh.read())
        except OSError:
            return None
    strips = [int(strip_value)] if strip_value is not None else [0, None]
    found = []
    for text in texts:
        for strip in strips:
            if strip is None:
                found += [os.path.basename(p) for p in _patch_paths(text, 0) + PATCH_INDEX.findall(text)]
            else:
                found += _patch_paths(text, strip) + [p for p in PATCH_INDEX.findall(text)]
    found = [p for p in dict.fromkeys(found) if p]
    if not found:
        return None  # 고칠 경로를 하나도 못 뽑으면 볼 수 없다
    return base, [(p, False) for p in ([] if opts.get("-o") or opts.get("--output") else found) + extra]


def _write_inner(tokens, command, base):
    """쓰기 판정을 다시 볼 셸 본문들: sh -c·eval 인자, 셸 heredoc·here-string, 셸 스크립트 파일, find -exec 명령."""
    name = os.path.basename(tokens[0])
    if name == "eval":
        return [" ".join(tokens[1:])]
    if name == "find":
        out = []
        for i, t in enumerate(tokens):
            if t in FIND_EXEC:
                sub = tokens[i + 1:]
                sub = sub[:sub.index("+")] if "+" in sub else sub
                if sub:
                    out.append(shlex.join(sub))
        return out
    if name in SHELLS:
        for j, t in enumerate(tokens[1:], 1):
            if t.startswith("-") and not t.startswith("--") and "c" in t[1:]:
                return [tokens[j + 1]] if j + 1 < len(tokens) else []
    found = _script_target(tokens)
    if not found or not found[0].endswith("shell") and found[0] != "shell":
        if not (found and found[0] == "exec"):
            return []
    kind, target = found
    if kind.startswith("heredoc"):
        return heredoc_bodies(command)
    if kind.startswith("herestring"):
        return [target]
    if kind in ("shell", "exec") and target and "$" not in target and (base or target.startswith("/")):
        path = resolve(target, base or "/")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return []
        if b"\0" in data[:4096]:
            return []
        text = data.decode("utf-8", errors="replace")
        if kind == "exec":
            first = text.split("\n", 1)[0]
            if first.startswith("#!") and not any(os.path.basename(w) in SHELLS for w in first[2:].split()):
                return []
        return [text]
    return []
