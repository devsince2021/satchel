"""플러그인 규칙 읽기 — 정본 `src/rules/*.json`(플러그인 뿌리)을 읽고 검사해 판정이 쓰는 꼴로 준다. 규칙 파일은 이것만 통해 읽는다.

- `flow.json`(`flow()`): 단계 이름과 차례·누가·필수·할 일 번호(`#N`)·시험 파일만 받는 단계(`steps`), 커밋 제목 꼴(`commit`),
  차례 규칙(`order`), 단계 사슬(`chain` — `Flow.prerequisite`), 리뷰어 기다림의 단계·보고 파일 짝(`reviews`).
- `files.json`(`files()`): 작업 세션이 쓰면 안 되는 워크트리 안 자리(`paths`) — open이 settings deny `Edit(…)`로 싣는다.
- `git.json`(`git()`): 작업 세션이 쓰면 안 되는 git 명령(`commands`) 하나의 목록. 막는 두 수단 — settings deny 앞머리(`Git.deny_bash`)와
  PreToolUse 훅 guard가 풀어 읽어 막는 목록(`Git.block_git`·`Git.block_git_args`, 세션 기록에 싣는다) — 을 둘 다 여기서 만든다.
- `tests.json`(`tests()`): 시험 파일 판정 — 꼴(`patterns`) 하나.
꼴은 `src/rules/README.md`. 파일이 없거나 깨졌거나 필수 키가 없거나 모르는 키·틀린 꼴이 있으면 RuleError로 멈춘다(말없이 느슨해지지 않게).
"""
import json
import os
import re

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # plugins/scroll(이 파일은 src/scripts/quest/libs/)
RULES_DIR = os.path.join(PLUGIN_ROOT, "src", "rules")
# 규칙 파일 자리 — 시험이 바꾼다
FLOW_FILE = os.path.join(RULES_DIR, "flow.json")
FILES_FILE = os.path.join(RULES_DIR, "files.json")
GIT_FILE = os.path.join(RULES_DIR, "git.json")
TESTS_FILE = os.path.join(RULES_DIR, "tests.json")
NOTE_KEY = "설명"  # 어느 규칙 파일에나 둘 수 있는 사람용 설명 칸(판정은 안 읽는다)
BY = ("리드", "작업 세션")
TODO = ("필수", "선택")
WRITTEN_BY = "quest merge"  # 이 스크립트가 쓰는 커밋의 단계(합치기 기록 커밋)
STEP_NAME = re.compile(r"[a-z][a-z0-9-]*")
STEP_KEYS = {"name", "stage", "by", "required", "todo", "tests_only", "written_by", "note", "start_after"}
# 단계 사슬(`chain.needs`) — 단계에 들어가려면(`quest step`)·그 단계를 커밋하려면(guard)·끝 확인 차례에서 앞에 있어야 할 단계를 정하는 법.
# previous_required: 단계 차례에서 그 단계 앞으로 거슬러 처음 만나는 필수 단계(단계의 `start_after`가 있으면 그것)
CHAIN_RULES = ("previous_required",)
# 차례 규칙·리뷰어 기다림: 종류마다 단계 이름을 담는 키(목록 값은 단계 이름 목록), 그 밖 키
ORDER_KINDS = {
    "todo_first": {"first": "step", "then": "step"},  # 할 일 #N마다 first 커밋과 then 커밋이 있고 첫 first가 첫 then보다 앞
    "no_code_before": {"steps": "steps", "until": "step"},  # 첫 until 커밋 앞의 steps 커밋은 구현 파일을 건드리지 않는다
    "exempt_fixed_at": {"step": "step", "record": "text"},  # 첫 step 커밋 때 record에 없던 TDD 예외는 까닭이 있어야 한다
}
REVIEW_KEYS = {"step": "step", "after": "step", "reports": "texts"}
REVIEW_KINDS = ("before_code", "after_code")
MERGE_STAGES = ("check", "deliver", "cleanup")  # 합치기 단계 — 코드(부명령 merge)가 이 차례로 돈다
MERGE_KEYS = ("name", "stage", "does", "takes")
SETTING_KEY = re.compile(r"[a-z]+\.[a-z_]+")  # `takes`의 설정 키 꼴(`묶음.키`)

_cache = {}


class RuleError(Exception):
    pass


class Flow:
    """검사를 마친 흐름 규칙. `data`는 파일 그대로(문서 생성이 쓴다)."""

    def __init__(self, data, path):
        self.data, self.path = data, path
        self.steps = data["steps"]
        self.names = tuple(s["name"] for s in self.steps)
        self.required = tuple(s["name"] for s in self.steps if s["required"])
        self.todo_steps = tuple(s["name"] for s in self.steps if "todo" in s)
        self.order = data["order"]
        self.chain_rule = data["chain"]["needs"]
        self.reviews = data["reviews"]
        self.merge = data["merge"]  # 합치기 단계 — [{name, stage, does, takes}], 차례는 MERGE_STAGES
        commit = data["commit"]
        self.title_shape = commit["title"]
        self.todo_ref = re.compile(commit["todo_ref"]["pattern"])
        self.todo_shape = commit["todo_ref"]["shape"]
        self.todo_many = commit["todo_ref"]["many"]
        self.bundle_sep = commit["bundle"]["sep"]
        self.other_id = commit["bundle"]["other_id"]
        self.merge_step = next(s["name"] for s in self.steps if s.get("written_by") == WRITTEN_BY)
        # 사람이 손으로 커밋하는 단계 — 누가(`by`)별. 합치기 기록 단계(`written_by`)는 부명령 merge만 남긴다
        self.hand_steps = {by: tuple(s["name"] for s in self.steps if s["by"] == by and "written_by" not in s) for by in BY}
        self.lead_steps = self.hand_steps["리드"]

    def todo_missing(self, step, nums):
        """할 일 번호가 필수인 단계(`todo: 필수`)인데 번호(`#N`)가 없나 — 끝 확인(checks/tdd)과 커밋 때 판정(guard)이 같이 쓴다."""
        return self.todo_required(step) and not nums

    def prerequisite(self, name):
        """단계 사슬의 앞 단계 — 단계에 들어가기(`quest step`)·커밋 때 확인(guard)·끝 확인 차례가 모두 이것 하나로 판정한다.
        단계의 `start_after`가 있으면 그것, 없으면 규칙(`chain.needs` = previous_required): 차례에서 앞으로 거슬러 처음 만나는 필수 단계.
        첫 단계면 None."""
        s = self.step(name)
        if "start_after" in s:
            return s["start_after"]
        before = self.steps[:self.names.index(name)]
        return next((p["name"] for p in reversed(before) if p["required"]), None)

    def merge_stage(self, name):
        """합치기 단계 이름(check·deliver·cleanup)의 문서 이름(예 `① 확인`)."""
        return next(m["stage"] for m in self.merge if m["name"] == name)

    def step(self, name):
        return next(s for s in self.steps if s["name"] == name)

    def todo_required(self, name):
        return self.step(name).get("todo") == "필수"

    def tests_only(self, name):
        return bool(self.step(name).get("tests_only"))

    def title(self, work, step):
        """커밋 제목 머리(`<ID> <단계>:`) — 뒤에 붙일 글은 부르는 쪽이."""
        return self.title_shape.replace("{id}", work).replace("{step}", step)

    def title_re(self, work, steps, bundle=False, rest=False):
        """제목 머리를 맞추는 정규식 — 그룹 1이 단계. bundle이면 묶음 제목 `<ID>·<ID> <단계>:`도 받는다.
        rest면 머리 뒤 글 전부가 그룹 2."""
        ident = re.escape(work)
        if bundle:
            sep = re.escape(self.bundle_sep)
            ident = rf"(?:{self.other_id}{sep})*{ident}(?:{sep}{self.other_id})*"
        alt = "|".join(re.escape(s) for s in steps)
        before, _, after = self.title_shape.partition("{id}")
        middle, _, tail = after.partition("{step}")
        pattern = "^" + re.escape(before) + ident + re.escape(middle) + f"({alt})" + re.escape(tail)
        return re.compile(pattern + ("(.*)$" if rest else ""))


def _fail(path, msg):
    raise RuleError(f"규칙 파일 {path}: {msg}")


def _need(path, obj, key, kind, where):
    if not isinstance(obj, dict) or key not in obj:
        _fail(path, f"{where}에 `{key}`이 없다")
    if not isinstance(obj[key], kind):
        _fail(path, f"{where}.{key}의 꼴이 틀렸다: {obj[key]!r}")
    return obj[key]


def _regex(path, text, where):
    try:
        re.compile(text)
    except re.error as e:
        _fail(path, f"{where}가 정규식이 아니다: {e}")


def _check_refs(path, obj, keys, names, where):
    """keys: {키: "step"|"steps"|"text"|"texts"}. 단계를 가리키는 값은 steps에 있어야 한다."""
    for key, kind in keys.items():
        if kind in ("step", "text"):
            value = _need(path, obj, key, str, where)
            if kind == "step" and value not in names:
                _fail(path, f"{where}.{key}의 단계 '{value}'가 steps에 없다")
        else:
            value = _need(path, obj, key, list, where)
            if not value or not all(isinstance(v, str) and v for v in value):
                _fail(path, f"{where}.{key}는 비지 않은 글 목록이어야 한다")
            if kind == "steps" and any(v not in names for v in value):
                _fail(path, f"{where}.{key}의 단계가 steps에 없다: {[v for v in value if v not in names]}")
    extra = set(obj) - set(keys)
    if extra:
        _fail(path, f"{where}에 모르는 키: {sorted(extra)}")


def validate(data, path):
    if not isinstance(data, dict):
        _fail(path, "JSON 객체가 아니다")
    steps = _need(path, data, "steps", list, "뿌리")
    if not steps:
        _fail(path, "steps가 비었다")
    names = []
    for i, s in enumerate(steps):
        where = f"steps[{i}]"
        name = _need(path, s, "name", str, where)
        if not STEP_NAME.fullmatch(name):
            _fail(path, f"{where}.name '{name}'은 소문자·숫자·`-`로 쓴다")
        if name in names:
            _fail(path, f"단계 '{name}'이 두 번 있다")
        names.append(name)
        _need(path, s, "stage", str, where)
        if _need(path, s, "by", str, where) not in BY:
            _fail(path, f"{where}.by는 {'·'.join(BY)} 가운데 하나")
        _need(path, s, "required", bool, where)
        if "todo" in s and s["todo"] not in TODO:
            _fail(path, f"{where}.todo는 {'·'.join(TODO)} 가운데 하나")
        if "tests_only" in s and not isinstance(s["tests_only"], bool):
            _fail(path, f"{where}.tests_only는 참·거짓")
        if "written_by" in s and s["written_by"] != WRITTEN_BY:
            _fail(path, f"{where}.written_by는 '{WRITTEN_BY}'만 쓴다")
        extra = set(s) - STEP_KEYS
        if extra:
            _fail(path, f"{where}에 모르는 키: {sorted(extra)}")
    for i, s in enumerate(steps):
        if "start_after" in s and s["start_after"] not in names[:i]:
            _fail(path, f"steps[{i}].start_after '{s['start_after']}'는 그 단계보다 앞의 단계여야 한다")
    chain = _need(path, data, "chain", dict, "뿌리")
    if _need(path, chain, "needs", str, "chain") not in CHAIN_RULES:
        _fail(path, f"chain.needs는 {'·'.join(CHAIN_RULES)} 가운데 하나다: {chain['needs']!r}")
    if set(chain) - {"needs", NOTE_KEY}:
        _fail(path, f"chain에 모르는 키: {sorted(set(chain) - {'needs', NOTE_KEY})}")
    if sum(1 for s in steps if s.get("written_by") == WRITTEN_BY) != 1:
        _fail(path, f"`written_by: {WRITTEN_BY}`인 단계(합치기 기록 커밋)가 꼭 하나 있어야 한다")
    commit = _need(path, data, "commit", dict, "뿌리")
    title = _need(path, commit, "title", str, "commit")
    if title.count("{id}") != 1 or title.count("{step}") != 1 or title.index("{id}") > title.index("{step}"):
        _fail(path, "commit.title에는 `{id}`와 그 뒤 `{step}`이 한 번씩 있어야 한다")
    ref = _need(path, commit, "todo_ref", dict, "commit")
    _regex(path, _need(path, ref, "pattern", str, "commit.todo_ref"), "commit.todo_ref.pattern")
    if re.compile(ref["pattern"]).groups != 1:
        _fail(path, "commit.todo_ref.pattern에는 번호 그룹이 하나 있어야 한다")
    _need(path, ref, "shape", str, "commit.todo_ref")
    _need(path, ref, "many", str, "commit.todo_ref")
    bundle = _need(path, commit, "bundle", dict, "commit")
    _need(path, bundle, "sep", str, "commit.bundle")
    _regex(path, _need(path, bundle, "other_id", str, "commit.bundle"), "commit.bundle.other_id")
    order = _need(path, data, "order", dict, "뿌리")
    for kind, keys in ORDER_KINDS.items():
        _check_refs(path, _need(path, order, kind, dict, "order"), keys, names, f"order.{kind}")
    if set(order) - set(ORDER_KINDS):
        _fail(path, f"order에 모르는 종류: {sorted(set(order) - set(ORDER_KINDS))}")
    reviews = _need(path, data, "reviews", dict, "뿌리")
    for kind in REVIEW_KINDS:
        _check_refs(path, _need(path, reviews, kind, dict, "reviews"), REVIEW_KEYS, names, f"reviews.{kind}")
    if set(reviews) - set(REVIEW_KINDS):
        _fail(path, f"reviews에 모르는 종류: {sorted(set(reviews) - set(REVIEW_KINDS))}")
    merge = _need(path, data, "merge", list, "뿌리")
    names = [m.get("name") if isinstance(m, dict) else None for m in merge]
    if tuple(names) != MERGE_STAGES:
        _fail(path, f"merge는 단계 {list(MERGE_STAGES)}를 이 차례로 적는다(지금 {names})")
    for i, m in enumerate(merge):
        where = f"merge[{i}]"
        for key in ("stage", "does"):
            if not _need(path, m, key, str, where).strip():
                _fail(path, f"{where}.{key}가 비었다")
        takes = _need(path, m, "takes", list, where)
        if not all(isinstance(t, str) and SETTING_KEY.fullmatch(t) for t in takes):
            _fail(path, f"{where}.takes는 설정 키(`묶음.키`) 목록이어야 한다: {takes!r}")
        extra = set(m) - set(MERGE_KEYS)
        if extra:
            _fail(path, f"{where}에 모르는 키: {sorted(extra)}")
    extra = set(data) - {"steps", "commit", "order", "chain", "reviews", "merge", NOTE_KEY}
    if extra:
        _fail(path, f"뿌리에 모르는 키: {sorted(extra)}")
    return data


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        _fail(path, f"읽지 못했다: {e}")
    except ValueError as e:
        _fail(path, f"JSON이 깨졌다: {e}")


def load(path):
    return Flow(validate(_read_json(path), path), path)


def _cached(kind, path, loader):
    """자리마다 한 번 읽는다(시험이 자리를 바꾸면 새로 읽는다)."""
    key = (kind, path)
    if key not in _cache:
        _cache[key] = loader(path)
    return _cache[key]


def flow():
    """지금 흐름 규칙(`FLOW_FILE`)."""
    return _cached("flow", FLOW_FILE, load)


# ---- 단순 규칙 파일(files·git·tests) 공통 검사 ----

def _strings(path, data, key, where=None, regex=False, empty=True):
    """data[key]가 글 목록인지(regex면 정규식인지) 본다."""
    where = where or key
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        _fail(path, f"{where}는 비지 않은 글 목록이어야 한다: {value!r}")
    if not empty and not value:
        _fail(path, f"{where}가 비었다")
    if regex:
        for v in value:
            _regex(path, v, f"{where}의 {v!r}")
    return list(value)


def _keys(path, data, keys):
    """뿌리가 사전이고 keys(와 설명 칸)만, 모두 있는지."""
    if not isinstance(data, dict):
        _fail(path, "JSON 객체가 아니다")
    missing = [k for k in keys if k not in data]
    if missing:
        _fail(path, f"뿌리에 {missing}이 없다")
    extra = set(data) - set(keys) - {NOTE_KEY}
    if extra:
        _fail(path, f"모르는 키: {sorted(extra)}")


class Files:
    """작업 세션이 쓰면 안 되는 워크트리 안 자리(`files.json`)."""
    KEYS = ("paths",)

    def __init__(self, data, path):
        _keys(path, data, self.KEYS)
        self.path = path
        self.paths = _strings(path, data, "paths")  # glob — open이 `Edit(<워크트리>/<자리>)` deny로 싣는다


GIT_COMMAND = re.compile(r"[a-z][a-z0-9-]*")  # git 하위 명령 이름
GIT_ENTRY_KEYS = ("command", "args", "why")
GIT_ENTRY_REQUIRED = ("command", "why")


class GitCommand:
    """막는 git 명령 하나 — 하위 명령 이름, 인자 조건(없으면 하위 명령 전체), 까닭."""

    def __init__(self, command, args, why):
        self.command, self.args, self.why = command, args, why


class Git:
    """작업 세션이 쓰면 안 되는 git 명령(`git.json`) — 한 명령은 한 번만. 막는 수단은 여기서 정한다(규칙 파일은 무엇만 적는다):
    - `deny_bash`: settings deny `Bash(<앞머리>:*)`의 앞머리 — `git <명령>`, 인자 조건이 있으면 인자마다 `git <명령> <인자>`.
    - `block_git`·`block_git_args`: guard가 명령을 풀어 읽어(-C 뒤·sh -c·eval·$( )·셸 본문 안까지) 막는 목록 — 인자 조건이 없는
      명령은 하위 명령째, 있으면 `<명령>:<인자>`. 세션 기록에 이 이름으로 싣는다(훅은 기록을 읽는다).
    두 수단 모두 모든 항목에 건다 — 앞머리로 못 잡는 꼴은 guard가, 훅이 안 걸리는 때는 deny가 막는다."""
    KEYS = ("commands",)

    def __init__(self, data, path):
        _keys(path, data, self.KEYS)
        self.path = path
        items = data["commands"]
        if not isinstance(items, list):
            _fail(path, f"commands는 목록이어야 한다: {items!r}")
        self.commands, seen = [], set()
        for i, item in enumerate(items):
            where = f"commands[{i}]"
            if not isinstance(item, dict):
                _fail(path, f"{where}은 JSON 객체여야 한다: {item!r}")
            missing = [k for k in GIT_ENTRY_REQUIRED if k not in item]
            if missing:
                _fail(path, f"{where}에 {missing}이 없다")
            extra = set(item) - set(GIT_ENTRY_KEYS)
            if extra:
                _fail(path, f"{where}의 모르는 키: {sorted(extra)}")
            name = item["command"]
            if not isinstance(name, str) or not GIT_COMMAND.fullmatch(name):
                _fail(path, f"{where}.command는 git 하위 명령 이름(소문자·숫자·`-`)이어야 한다: {name!r}")
            if not isinstance(item["why"], str) or not item["why"].strip():
                _fail(path, f"{where}.why는 비지 않은 글이어야 한다: {item['why']!r}")
            args = item.get("args")
            if args is not None and (not isinstance(args, list) or not args or not all(
                    isinstance(a, str) and a and not any(c.isspace() for c in a) and ":" not in a for a in args)):
                _fail(path, f"{where}.args는 빈칸·`:` 없는 인자 글의 비지 않은 목록이어야 한다(인자 조건이 없으면 키를 뺀다): {args!r}")
            if name in seen:
                _fail(path, f"{where}: {name}가 두 번 적혔다 — 한 명령은 한 항목에(인자 조건은 args 하나에)")
            seen.add(name)
            self.commands.append(GitCommand(name, list(args or ()), item["why"]))
        self.deny_bash = [f"git {c.command} {a}" if a else f"git {c.command}"
                          for c in self.commands for a in (c.args or [None])]
        self.block_git = [c.command for c in self.commands if not c.args]
        self.block_git_args = [f"{c.command}:{a}" for c in self.commands for a in c.args]


class Tests:
    """시험 파일 판정(`tests.json`) — 꼴(`patterns`) 하나. 하나라도 맞으면 시험 파일."""
    KEYS = ("patterns",)

    def __init__(self, data, path):
        _keys(path, data, self.KEYS)
        self.path = path
        self.patterns = _strings(path, data, "patterns", regex=True)  # 시험 파일로 치는 경로(하나라도 맞으면)

    def is_test_file(self, path):
        return any(re.search(p, path) for p in self.patterns)


def files():
    """지금 작업 세션이 쓰면 안 되는 자리(`FILES_FILE`)."""
    return _cached("files", FILES_FILE, lambda p: Files(_read_json(p), p))


def git():
    """지금 작업 세션이 쓰면 안 되는 git 명령(`GIT_FILE`)."""
    return _cached("git", GIT_FILE, lambda p: Git(_read_json(p), p))


def tests():
    """지금 시험 파일 판정(`TESTS_FILE`)."""
    return _cached("tests", TESTS_FILE, lambda p: Tests(_read_json(p), p))


def load_all():
    """규칙 파일을 모두 읽는다 — 사람이 부르는 부명령이 판정 전에 불러 깨진 파일이면 먼저 멈춘다(RuleError)."""
    return flow(), files(), git(), tests()
