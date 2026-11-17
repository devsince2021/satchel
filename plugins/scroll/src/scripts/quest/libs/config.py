"""quest 설정 값 — 설정 파일(`.satchel/quest.json`, 읽기·받는 키 검사는 공용 `libs/settings.py`)에서 quest가 쓰는 값과
quest 전용 고정·셈 값, 거기서 나오는 꼴(정규식·경로·메시지). 경로·이름은 이것만 통해 얻는다.

quest가 꼭 요청하는 키는 `branches.integration`·`session.terminal`(없으면 ConfigError — 사람이 부르는 부명령은 멈추고 훅은 판정 불가로
지나간다). `session.terminal`은 플러그인 규칙 `src/presets/terminals.json`의 프리셋 이름이나 `custom`이어야 하고, `session.launch`·`close`는
custom일 때만 받는다. 그 밖의 값은 받지 않는다 — 아래 "고정"과 "셈"이 코드 안 한 곳이다. 막기 목록·시험 파일 판정·바뀐 규칙 문장
확인은 프로젝트 설정이 아니라 플러그인 규칙(`src/rules/*.json`, `quest/libs/rules.py`), 터미널 프리셋은 플러그인 프리셋(`src/presets/terminals.json`, `quest/libs/presets.py`)이다.
Python 3.9 표준 라이브러리만 쓴다.
"""
import os
import re
import shlex

from libs import git as gitlib
from libs import settings
from libs.settings import CONFIG_REL, REQUIRED, ConfigError, config_path, present  # noqa: F401  부르는 쪽이 이 모듈 하나로 쓰게
from quest.libs import presets

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))  # plugins/scroll(이 파일은 src/scripts/quest/libs/)

KEYS = settings.KEYS  # 받는 키 목록의 정본은 공용 libs/settings.py
GROUPS = ("branches", "quest", "session", "deliver")  # quest가 읽는 묶음(deliver는 quest merge가 deliver에 넘긴다)
NEEDS = ("branches.integration", "session.terminal")  # quest가 꼭 요청하는 키
CUSTOM = presets.CUSTOM
CUSTOM_ONLY = ("session.launch", "session.close")

# ---- 받지 않는 값: 고정 ----
ID_PREFIX = "Q"  # 작업 ID `Q-NNN`
ID_DIGITS = 3
ID_PATTERN = rf"{re.escape(ID_PREFIX)}-\d{{{ID_DIGITS}}}"  # 작업 ID 정규식 조각(묶음 없음)
CARRY_PREFIX = "C"  # 넘길 일 장부 줄 ID `C-NNN`
SENT_ADDRESSES = ("SendMessage",)  # 장부 `넘김` 근거 칸에서 받는 쪽 주소로 치는 낱말(정규식 조각)
WORK_BRANCH = "quest/{folder}"  # 작업 브랜치 꼴. {folder} = <ID>-<슬러그>
WORKTREE = "{parent}/{repo}-{id_lower}"  # 작업 워크트리 자리 — 리드 저장소 옆
TITLE = "quest {id}"  # 작업 세션 이름(claude --name)
PERMISSION_FLAG = "--dangerously-skip-permissions"  # 작업 세션 권한 — 늘 이것(세션 deny와 훅은 그대로 걸린다)
ENTRY = os.path.join(PLUGIN_ROOT, "src", "scripts", "quest", "main.py")  # quest 입구 — 훅·시작 지시·안내 글은 `python3 <ENTRY> <부명령>`으로 부른다
REQUIREMENTS_TEMPLATE = os.path.join(PLUGIN_ROOT, "src", "skills", "quest", "templates", "requirements.md")  # 요구사항 틀
RECORDS_IN_GIT = ("satchel", "quest-sessions")  # 세션 기록 자리 — <git 공통 자리>/satchel/quest-sessions
# 세션 환경 변수: 붙이지 않는다(claude 명령은 여는 쪽 환경을 그대로 받는다)

# ---- 받지 않는 값: 셈(받는 키에서) ----
REMOTE_PREFIX = "origin/"  # 작업 범위 기준 후보 = origin/<branches.integration>
QUEST_LIST = "README.md"  # 작업 목록 = <quest.quests>/README.md
CARRYOVER = "carryover.md"  # 넘길 일 장부 = <quest.quests>/carryover.md
DECISIONS = "decisions"  # 결정 폴더 = <quest.quests의 부모>/decisions


def project_root(cwd):
    """cwd가 든 git 작업본 꼭대기. git 밖이면 None."""
    return gitlib.project_root(cwd)


def load(root=None):
    """root(저장소 뿌리)의 설정. 파일이 없거나 root가 None이면 빈 설정으로 셈한다 — 필수 키가 없어 ConfigError."""
    return build(settings.read(root), root)


def build(override, root=None):
    """적은 값을 검사하고 기본값을 채운 Config. 필수 키가 없으면 그것을 적으라는 ConfigError."""
    values, written = settings.values(override, GROUPS, NEEDS, root)
    terminal = values["session.terminal"]
    names = presets.terminals().names  # 규칙 파일이 깨졌으면 RuleError
    if terminal not in names:
        raise ConfigError(f"session.terminal: 모르는 값 {terminal!r} — {' · '.join(names)} 가운데 하나")
    for path in CUSTOM_ONLY:
        if path in written and terminal != CUSTOM:
            raise ConfigError(f"{path}: session.terminal이 {CUSTOM}일 때만 받는다(지금 {terminal!r})")
    if terminal == CUSTOM and not values["session.launch"].strip():
        raise ConfigError(f"session.launch: session.terminal이 {CUSTOM}이면 띄울 명령 틀을 적어야 한다")
    RuleDocs(values["quest.rule_docs"])  # 꼴 확인 — 틀리면 ConfigError
    return Config(values, root)


class RuleDocs:
    """"바뀐 규칙 문장" 확인 — 설정 `quest.rule_docs`({patterns, optional_prefix, search_dirs}). patterns가 비거나 없으면 꺼짐.
    - patterns: 규칙 문서로 치는 경로 정규식(저장소 뿌리 기준). 작업 범위에서 이 문서를 바꿨으면 회고 `## 바뀐 규칙 문장`에 줄이 있어야 한다.
    - optional_prefix: 회고 줄의 파일 자리에서 생략해도 되는 머리.
    - search_dirs: 문서·규칙 리뷰어가 낡은 언급을 찾을 폴더·파일(비면 그 찾기를 건너뛴다)."""
    KEYS = ("patterns", "optional_prefix", "search_dirs")
    WHERE = "quest.rule_docs"

    def __init__(self, data):
        extra = set(data) - set(self.KEYS)
        if extra:
            raise ConfigError(f"모르는 키: {', '.join(f'{self.WHERE}.{k}' for k in sorted(extra))}")
        self.patterns = self._strings(data, "patterns", regex=True)
        prefix = data.get("optional_prefix", "")
        if not isinstance(prefix, str):
            raise ConfigError(f"{self.WHERE}.optional_prefix는 글이어야 한다: {prefix!r}")
        self.optional_prefix = prefix
        self.search_dirs = self._strings(data, "search_dirs")

    def _strings(self, data, key, regex=False):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise ConfigError(f"{self.WHERE}.{key}는 비지 않은 글 목록이어야 한다: {value!r}")
        for v in value if regex else ():
            try:
                re.compile(v)
            except re.error as e:
                raise ConfigError(f"{self.WHERE}.{key}의 {v!r}가 정규식이 아니다: {e}") from e
        return list(value)

    @property
    def on(self):
        return bool(self.patterns)

    def is_rule_doc(self, path):
        return any(re.search(p, path) for p in self.patterns)


def _sibling(path, name):
    """path(기록 폴더)와 같은 부모 아래 name — 부모가 없으면 name."""
    parent = os.path.dirname(path.rstrip("/"))
    return f"{parent}/{name}" if parent else name


def work_from_branch(branch):
    """작업 브랜치 이름(고정 꼴 `quest/<ID>-<슬러그>`)에서 작업 ID. 작업 브랜치가 아니면 None — 설정 없이 가른다."""
    prefix, _, tail = WORK_BRANCH.partition("{folder}")
    m = re.fullmatch(re.escape(prefix) + rf"({ID_PATTERN})-.+" + re.escape(tail), branch or "")
    return m.group(1) if m else None


class Config:
    """설정 값(`values` — quest가 읽는 키마다 하나)과 거기서 나오는 꼴(정규식·경로·메시지)."""

    def __init__(self, values, root=None):
        self.values = values
        self.root = os.path.realpath(root) if root else None
        quests = values["quest.quests"]
        self.paths = {  # 저장소 뿌리 기준 상대 경로 — 받은 것과 셈한 것
            "quests": quests,
            "quest_list": quests.rstrip("/") + "/" + QUEST_LIST,
            "carryover": quests.rstrip("/") + "/" + CARRYOVER,
            "decisions": _sibling(quests, DECISIONS),
            "guide_docs": values["quest.guide_docs"],
        }

    def get(self, dotted):
        return self.values[dotted]

    @property
    def rule_docs(self):
        """"바뀐 규칙 문장" 확인(설정 `quest.rule_docs`) — `.on`이 거짓이면 꺼짐."""
        return RuleDocs(self.values["quest.rule_docs"])

    # ---- 작업 ID ----
    prefix = ID_PREFIX
    digits = ID_DIGITS
    id_pattern = ID_PATTERN

    def is_id(self, text):
        return bool(re.fullmatch(self.id_pattern, text or ""))

    def id_num(self, work):
        return int(work.split("-", 1)[1])

    def fmt_id(self, n):
        return f"{self.prefix}-{n:0{self.digits}d}"

    @property
    def id_shape(self):
        """사람이 읽는 ID 꼴(Q-NNN)."""
        return f"{self.prefix}-{'N' * self.digits}"

    # ---- 장부 ID ----
    carry_prefix = CARRY_PREFIX
    carry_pattern = rf"{re.escape(CARRY_PREFIX)}-\d{{3}}"
    carry_shape = f"{CARRY_PREFIX}-NNN"
    sent_addresses = SENT_ADDRESSES

    # ---- 리드·메시지 ----
    @property
    def lead(self):
        return self.values["quest.lead"]

    def to_lead(self, work, text=""):
        return f"[{work} → {self.lead}]" + (f" {text}" if text else "")

    def from_lead(self, work, text=""):
        return f"[{self.lead} → {work}]" + (f" {text}" if text else "")

    # ---- 브랜치 ----
    @property
    def integration(self):
        return self.values["branches.integration"]

    @property
    def remote_integration(self):
        return REMOTE_PREFIX + self.integration

    def work_branch(self, folder):
        self.split_folder(folder)  # 꼴 확인
        return WORK_BRANCH.format(folder=folder)

    def split_folder(self, folder):
        m = re.match(rf"({self.id_pattern})-(.*)$", folder)
        if not m:
            raise ConfigError(f"기록 폴더 이름이 `<ID>-<슬러그>` 꼴이 아니다: {folder}")
        return m.group(1), "", m.group(2)

    def work_from_branch(self, branch):
        return work_from_branch(branch)

    # ---- 경로(저장소 뿌리 기준 상대 → 절대) ----
    def rel(self, key):
        return self.paths[key]

    def path(self, key, root=None):
        base = root or self.root
        value = self.paths[key]
        return os.path.join(base, value) if base else value

    def requirements_template(self, root=None):
        return REQUIREMENTS_TEMPLATE

    # ---- 세션 ----
    @property
    def terminal(self):
        return self.values["session.terminal"]

    @property
    def model(self):
        return self.values["session.model"]

    def worktree_for(self, top, work, folder):
        return os.path.normpath(WORKTREE.format(parent=os.path.dirname(top), repo=os.path.basename(top), id_lower=work.lower()))

    def title_for(self, work, slug=""):
        return TITLE.format(id=work)

    def records_dir(self, root=None):
        return records_dir(root or self.root)


def records_dir(base):
    """작업 세션 기록 자리(작업마다 `<자리>/<ID>/`) — `<git 공통 자리>/satchel/quest-sessions`."""
    try:
        common = gitlib.common_dir(base)
    except gitlib.GitError as e:
        raise ConfigError(str(e)) from e
    return os.path.join(common, *RECORDS_IN_GIT)


def fill(template, values):
    """셸 명령 틀의 자리표 `{이름}`을 셸 따옴표로 싼 값으로 바꾼다. 글자 그대로의 중괄호는 `{{`·`}}`.
    모르는 자리표는 ConfigError."""
    def sub(m):
        if m.group(0) in ("{{", "}}"):
            return m.group(0)[0]
        name = m.group(1)
        if name not in values:
            raise ConfigError(f"명령 틀의 모르는 자리표 {{{name}}} — 쓸 수 있는 것: {', '.join(sorted(values))}")
        return shlex.quote(str(values[name]))
    return re.sub(r"\{\{|\}\}|\{([a-z_]+)\}", sub, template)
