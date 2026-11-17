"""설정 파일 읽기 — 프로젝트 저장소 뿌리의 `.satchel/quest.json`을 찾고 읽어 받는 키를 검사하는 한 곳. quest·deliver가 같이 쓴다.

파일 하나를 quest·deliver가 나눠 쓰므로 받는 키 목록(`KEYS`)과 걷은 옛 키의 행방(`MOVED`)은 여기 하나다. 부르는 쪽은 자기가 쓸
묶음과 꼭 있어야 할 키만 요청한다(`values(data, groups, required)`). 어느 쪽이 부르든 파일 전체에서 모르는 키(걷은 옛 키 포함 — 바뀐
곳을 한 줄 덧붙인다)·꼴이 틀린 값은 ConfigError로 멈춘다(오타가 말없이 기본값으로 돌아가지 않게). 키의 뜻은 플러그인 README "설정" 표.
이 모듈은 quest·deliver를 모른다. Python 3.9 표준 라이브러리만.
"""
import copy
import json
import os

CONFIG_REL = os.path.join(".satchel", "quest.json")
OLD_CONFIG_REL = os.path.join("." + "-".join(("agent", "kit")), "quest.json")  # 옛 자리 — 여기에만 있으면 새 자리로 옮기라고 멈춘다

# ---- 받는 키 — 뜻은 README "설정" 표가 정본이다. 바꾸면 그 표도 고친다 ----
REQUIRED = None  # 기본값 자리에 이것이면 요청한 쪽이 꼭 적어야 한다고 할 수 있는 키
KEYS = {
    # branches — quest·deliver 같이 씀
    "branches.integration": (str, REQUIRED),  # 통합 브랜치 — 리드 체크아웃이 이 브랜치여야 열고 합친다
    # quest — quest만
    "quest.quests": (str, ".agents/quests"),  # 기록 폴더 — 그 아래 `<ID>-<슬러그>/` 하나가 작업 하나
    "quest.guide_docs": (list, ["AGENTS.md"]),  # 결정·검토 전에 읽을 문서(규칙 색인·사용자 결정 패턴 등)
    "quest.lead": (str, "lead"),  # 메시지 꼴 `[<ID> → <리드>] …`·`[<리드> → <ID>] …`의 리드 이름
    "quest.rule_docs": (dict, {}),  # 어느 파일이 규칙 문서인가 {patterns, optional_prefix, search_dirs} — 비거나 없으면 "바뀐 규칙 문장" 확인 꺼짐
    # session — quest 작업 세션
    "session.terminal": (str, REQUIRED),  # 작업 세션을 띄우고 닫는 터미널 — 플러그인 규칙 src/presets/terminals.json의 프리셋 이름 또는 custom
    "session.model": (str, "opus"),  # 작업 세션 claude `--model`
    "session.launch": (str, ""),  # session.terminal이 custom일 때만 — 작업 세션을 띄울 셸 명령 틀
    "session.close": (str, ""),  # session.terminal이 custom일 때만 — 합친 뒤 작업 세션을 닫을 셸 명령 틀
    # deliver — 브랜치 하나를 통합 브랜치에 넣기(quest merge도 이것을 쓴다)
    "deliver.verify": (str, ""),  # 합치기 전에 브랜치 워크트리에서 돌릴 셸 명령. 종료 코드 0이어야 합친다. 빈 글이면 건너뜀
}
NONEMPTY = ("branches.integration", "session.terminal", "quest.quests", "quest.lead", "session.model")
REQUIRED_HINT = {
    "branches.integration": '{"branches": {"integration": "<통합 브랜치>"}}',
    "session.terminal": '{"session": {"terminal": "<none·tmux·orca·custom 가운데 하나>"}}',
}

# ---- 걷은 옛 키 — 설정에 있으면 모르는 키로 멈추고 무엇으로 바뀌었는지 덧붙인다 ----
_FIXED = "받지 않는다 — 고정"
_RULES = "프로젝트 설정에서 뺐다 — 플러그인 규칙"
MOVED = {
    "paths.quests": "quest.quests로 옮겼다",
    "paths.guide_docs": "quest.guide_docs로 옮겼다",
    "lead.name": "quest.lead로 옮겼다",
    "merge.verify": "deliver.verify로 옮겼다",
    "quest.id_prefix": f"{_FIXED}(`Q`)",
    "quest.id_digits": f"{_FIXED}(3자리)",
    "carryover.id_prefix": f"{_FIXED}(`C`)",
    "carryover.sent_addresses": f"{_FIXED}(SendMessage)",
    "branches.remote_integration": "받지 않는다 — `origin/<branches.integration>`으로 셈한다",
    "branches.work": f"{_FIXED}(`quest/{{folder}}`)",
    "paths.quest_list": "받지 않는다 — `<quest.quests>/README.md`로 셈한다",
    "paths.carryover": "받지 않는다 — `<quest.quests>/carryover.md`로 셈한다",
    "paths.decisions": "받지 않는다 — `<quest.quests의 부모>/decisions`로 셈한다",
    "paths.requirements_template": f"{_FIXED}(플러그인 src/skills/quest/templates/requirements.md)",
    "session.worktree": f"{_FIXED}(`{{parent}}/{{repo}}-{{id_lower}}`)",
    "session.title": f"{_FIXED}(`quest {{id}}`)",
    "session.record_dir": f"{_FIXED}(<git 공통 자리>/satchel/quest-sessions)",
    "session.claude_args": "session.model로 바뀌었다(권한은 늘 --dangerously-skip-permissions, --plugin-dir은 open이 더한다)",
    "session.env": f"{_FIXED}(붙이지 않는다)",
    "session.deny_paths": f"{_RULES} src/rules/files.json",
    "session.deny_bash": f"{_RULES} src/rules/git.json",
    "session.block_git": f"{_RULES} src/rules/git.json",
    "session.block_git_args": f"{_RULES} src/rules/git.json",
    "tests": f"{_RULES} src/rules/tests.json",  # 묶음째 적은 꼴
    "tests.patterns": f"{_RULES} src/rules/tests.json",
    "tests.areas": "걷었다 — 시험 파일은 src/rules/tests.json의 patterns 하나로 가른다(못 가르면 TDD 예외)",
    "tests.companions": "걷었다 — 시험 커밋은 시험 파일만 받는다(못 가르면 TDD 예외)",
    "rules.patterns": "quest.rule_docs.patterns로 옮겼다",
    "rules.optional_prefix": "quest.rule_docs.optional_prefix로 옮겼다",
    "rules.search_dirs": "quest.rule_docs.search_dirs로 옮겼다",
}


class ConfigError(Exception):
    pass


def config_path(root):
    return os.path.join(root, CONFIG_REL)


def present(root):
    """root(저장소 뿌리)에 설정 파일이 있나 — 옛 자리에만 있어도 참(읽으면 옮기라고 멈춘다)."""
    return bool(root) and any(os.path.isfile(os.path.join(root, rel)) for rel in (CONFIG_REL, OLD_CONFIG_REL))


def read(root=None):
    """root(저장소 뿌리)의 설정 파일 내용(사전). 파일이 없거나 root가 None이면 빈 사전. 깨진 JSON·옛 자리에만 있는 설정은 ConfigError."""
    if not root:
        return {}
    path = config_path(root)
    if not os.path.exists(path):
        if os.path.isfile(os.path.join(root, OLD_CONFIG_REL)):
            raise ConfigError(f"설정 파일을 `{CONFIG_REL}`으로 옮겨라 — 지금은 `{OLD_CONFIG_REL}`에 있다({root})")
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise ConfigError(f"설정을 읽지 못했다({path}): {e}") from e


def _unknown(path):
    hint = MOVED.get(path)
    if hint is None:  # 옛 묶음 이름만 적은 꼴(`{"tests": …}`)이면 그 아래 옛 키들의 행방
        under = sorted({v for k, v in MOVED.items() if k.startswith(path + ".")})
        hint = " / ".join(under) if len(under) == 1 else None
    return ConfigError(f"모르는 키: {path}" + (f" — {hint}" if hint else ""))


def flatten(data):
    """설정 사전 → {"묶음.키": 값}. 꼴이 틀리거나 모르는 키면 ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError("설정: 사전이어야 한다")
    groups = {k.split(".")[0] for k in KEYS}
    out = {}
    for group, body in data.items():
        if group not in groups:  # 걷은 묶음이면 그 안 첫 키로 알린다(어디로 갔는지 키마다 다르다)
            raise _unknown(f"{group}.{next(iter(body))}" if isinstance(body, dict) and body else group)
        if not isinstance(body, dict):
            raise ConfigError(f"{group}: 사전이어야 한다")
        for key, value in body.items():
            path = f"{group}.{key}"
            if path not in KEYS:
                raise _unknown(path)
            out[path] = value
    return out


def _check_value(path, value, want):
    if not isinstance(value, want):
        raise ConfigError(f"{path}: {dict(((str, '글'), (list, '목록'), (dict, '사전')))[want]}이어야 한다: {value!r}")
    if want is list and not all(isinstance(x, str) for x in value):
        raise ConfigError(f"{path}: 글 목록이어야 한다: {value!r}")
    if path in NONEMPTY and not value.strip():
        raise ConfigError(f"{path}: 비어 있으면 안 된다")


def values(data, groups, required, root=None):
    """data(설정 사전)를 검사해 요청한 묶음(groups)의 키마다 값(적은 값, 없으면 기본값)을 준다 → ({"묶음.키": 값}, 적은 키 집합).
    모르는 키·틀린 꼴은 파일 전체에서 본다. required 가운데 없는 키가 있으면 그것을 적으라는 ConfigError."""
    flat = flatten(data)
    missing = [k for k in required if k not in flat]
    if missing:
        where = f"`{CONFIG_REL}`" + (f"({config_path(root)})" if root else "")
        raise ConfigError("설정에 " + "·".join(missing) + f"을 적어라 — {where}에 "
                          + ", ".join(REQUIRED_HINT.get(k, f'"{k}"') for k in missing))
    out = {}
    for path, (want, default) in KEYS.items():
        if path in flat:
            _check_value(path, flat[path], want)
        if path.split(".")[0] not in groups:
            continue
        out[path] = copy.deepcopy(flat[path] if path in flat else default)
    return out, set(flat)
