"""실행 수단 프리셋 읽기 — 정본 `src/presets/*.json`(플러그인 뿌리)을 읽고 검사한다. 지금은 `terminals.json`(`terminals()`) 하나:
작업 세션을 띄우고 닫는 터미널 프리셋. `rules/`가 seam이 지키게 하는 규칙이라면 `presets/`는 프로젝트가 고를 수 있는 실행 수단이다
(설정 `session.terminal`이 이름으로 고른다). 꼴은 `src/rules/README.md`의 "src/presets/terminals.json 꼴". 깨졌거나 틀린 꼴이면 RuleError로 멈춘다
(규칙 파일과 같은 오류 — 사람이 부르는 부명령은 판정 전에 멈추고 훅은 판정 불가로 지나간다). 돌리는 코드는 `seam/libs/terminals.py`.
"""
import os
import re

from seam.libs.rules import NOTE_KEY, PLUGIN_ROOT, RuleError, _cached, _fail, _keys, _read_json, _regex  # noqa: F401  같은 검사 부품

PRESETS_DIR = os.path.join(PLUGIN_ROOT, "src", "presets")
TERMINALS_FILE = os.path.join(PRESETS_DIR, "terminals.json")  # 시험이 바꾼다

PLACEHOLDER = re.compile(r"\{\{|\}\}|\{(env:[A-Za-z_][A-Za-z0-9_]*|[a-z_]+)\}")
LAUNCH_NAMES = ("bin", "title", "command", "worktree", "id")  # 띄우기·찾기 틀의 자리표(그 밖에 {env:<이름>})
CLOSE_NAMES = ("bin", "title", "worktree", "id", "handle")  # 닫기 틀의 자리표
PRESET_KEYS = ("bin", "env", "launch", "handle", "find", "lost", "close")
FIND_KEYS = ("argv", "list", "title", "handle", "tries", "wait_seconds")
HANDLE_WAYS = ("json", "regex", "last_line")
CUSTOM = "custom"  # 프리셋이 아니라 프로젝트 설정 session.launch·close 틀을 쓰는 이름 — 프리셋 이름으로 쓸 수 없다


def fill_argv(argv, values, env=None):
    """명령 틀(글 목록)의 자리표를 채운 목록 — 셸을 거치지 않으므로 따옴표로 싸지 않는다. 글자 그대로의 중괄호는 `{{`·`}}`.
    `{env:<이름>}`은 env(없으면 os.environ)의 값. 없는 자리표·없는 환경 변수는 KeyError."""
    env = os.environ if env is None else env

    def sub(m):
        if m.group(0) in ("{{", "}}"):
            return m.group(0)[0]
        name = m.group(1)
        if name.startswith("env:"):
            return env[name[4:]]
        return str(values[name])
    return [PLACEHOLDER.sub(sub, a) for a in argv]


def _argv(path, value, where, names, env_names):
    if not isinstance(value, list) or not value or not all(isinstance(a, str) for a in value):
        _fail(path, f"{where}는 비지 않은 글 목록(명령 틀)이어야 한다")
    for a in value:
        for m in PLACEHOLDER.finditer(a):
            name = m.group(1)
            if name is None:
                continue
            if name.startswith("env:"):
                if name[4:] not in env_names:
                    _fail(path, f"{where}의 {{{name}}} — env에 적지 않은 환경 변수다")
            elif name not in names:
                _fail(path, f"{where}의 모르는 자리표 {{{name}}} — 쓸 수 있는 것: {', '.join(names)}, env:<이름>")
    return value


class Terminals:
    """터미널 프리셋(`terminals.json`). presets[이름]은 검사를 마친 사전."""

    def __init__(self, data, path):
        _keys(path, data, ("presets",))
        self.path = path
        presets = data["presets"]
        if not isinstance(presets, dict) or not presets:
            _fail(path, "presets는 비지 않은 사전이어야 한다")
        if CUSTOM in presets:
            _fail(path, f"`{CUSTOM}`은 프로젝트 설정 session.launch·close를 쓰는 이름이라 프리셋으로 둘 수 없다")
        self.presets = {}
        for name, p in presets.items():
            if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
                _fail(path, f"프리셋 이름 '{name}'은 소문자·숫자·`-`로 쓴다")
            self.presets[name] = self._preset(path, name, p)

    @staticmethod
    def _preset(path, name, p):
        where = f"presets.{name}"
        if not isinstance(p, dict):
            _fail(path, f"{where}는 사전이어야 한다")
        extra = set(p) - set(PRESET_KEYS) - {NOTE_KEY}
        if extra:
            _fail(path, f"{where}에 모르는 키: {sorted(extra)}")
        if "launch" not in p:  # 띄우지 않는 프리셋(명령만 찍는다) — 다른 키를 두지 않는다
            if set(p) - {NOTE_KEY}:
                _fail(path, f"{where}: launch가 없는 프리셋(명령만 찍음)에는 {sorted(set(p) - {NOTE_KEY})}을 두지 않는다")
            return {"launch": None}
        for key in ("bin", "launch", "handle"):
            if key not in p:
                _fail(path, f"{where}에 `{key}`이 없다")
        b = p["bin"]
        if (not isinstance(b, dict) or set(b) - {"name", "fallbacks"} or not isinstance(b.get("name"), str) or not b["name"]
                or not isinstance(b.get("fallbacks", []), list) or not all(isinstance(x, str) for x in b.get("fallbacks", []))):
            _fail(path, f"{where}.bin은 {{\"name\": <실행 파일 이름>, \"fallbacks\": [<절대 경로>…]}}이어야 한다")
        env = p.get("env", {})
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in env.items()):
            _fail(path, f"{where}.env는 {{<환경 변수>: <없을 때 알릴 글>}}이어야 한다")
        _argv(path, p["launch"], f"{where}.launch", LAUNCH_NAMES, env)
        ways = p["handle"]
        if not isinstance(ways, list) or not ways:
            _fail(path, f"{where}.handle은 핸들 꺼내는 법의 비지 않은 목록이어야 한다")
        for i, w in enumerate(ways):
            if not isinstance(w, dict) or len(w) != 1 or next(iter(w)) not in HANDLE_WAYS or not isinstance(next(iter(w.values())), str):
                _fail(path, f"{where}.handle[{i}]는 {{{' | '.join(HANDLE_WAYS)}: <글>}} 하나여야 한다")
            way, value = next(iter(w.items()))
            if way in ("regex", "last_line"):
                _regex(path, value, f"{where}.handle[{i}].{way}")
        find = p.get("find")
        if find is not None:
            if not isinstance(find, dict) or set(find) != set(FIND_KEYS):
                _fail(path, f"{where}.find에는 {list(FIND_KEYS)}가 모두(그것만) 있어야 한다")
            _argv(path, find["argv"], f"{where}.find.argv", LAUNCH_NAMES, env)
            for key in ("list", "title", "handle"):
                if not isinstance(find[key], str) or not find[key]:
                    _fail(path, f"{where}.find.{key}는 글이어야 한다")
            if isinstance(find["tries"], bool) or not isinstance(find["tries"], int) or not 1 <= find["tries"] <= 10:
                _fail(path, f"{where}.find.tries는 1~10 정수")
            if isinstance(find["wait_seconds"], bool) or not isinstance(find["wait_seconds"], (int, float)) or not 0 <= find["wait_seconds"] <= 30:
                _fail(path, f"{where}.find.wait_seconds는 0~30")
        if "lost" in p and (not isinstance(p["lost"], str) or not p["lost"]):
            _fail(path, f"{where}.lost는 글이어야 한다")
        close = p.get("close", [])
        if not isinstance(close, list):
            _fail(path, f"{where}.close는 명령 틀의 목록이어야 한다")
        for i, step in enumerate(close):
            _argv(path, step, f"{where}.close[{i}]", CLOSE_NAMES, env)
        return {"bin": {"name": b["name"], "fallbacks": list(b.get("fallbacks", []))}, "env": dict(env),
                "launch": list(p["launch"]), "handle": [dict(w) for w in ways], "find": dict(find) if find else None,
                "lost": p.get("lost", "탭·창은 떴을 수 있다 — 찾아서 세션 기록 session.json의 handle에 적는다"),
                "close": [list(s) for s in close]}

    @property
    def names(self):
        """설정 session.terminal에 쓸 수 있는 이름 — 프리셋들과 custom."""
        return (*self.presets, CUSTOM)


def terminals():
    """지금 터미널 프리셋(`TERMINALS_FILE`)."""
    return _cached("terminals", TERMINALS_FILE, lambda p: Terminals(_read_json(p), p))
