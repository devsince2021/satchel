"""시험 도우미 — 시험이 함께 쓰는 설정과 규칙 사본을 준다(시험 묶음 test/__init__.py가 읽어 둔다).
설정은 기본값과 다른 값(하위 폴더 `svc/` 아래 기록, 통합 브랜치 `dev/main`)을 일부러 써서 경로·이름이 설정에서만 오는지 본다.
설정의 "바뀐 규칙 문장" 확인(`quest.rule_docs`)은 켠다(기본값은 꺼짐 — 끈 설정은 `svc(rule_docs=None)`).
플러그인 규칙 `src/rules/tests.json`도 이 시험 프로세스 안에서는 플러그인 값과 다른 사본(SVC_RULES — 더 좁은 꼴)으로 바꿔
판정 값이 규칙 파일에서만 오는지 본다. 한 시험만 다른 규칙이 필요하면 `use_rules`."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # plugins/scroll
SRC = os.path.join(PLUGIN, "src", "scripts")  # 공용 libs·quest·deliver 묶음이 든 자리
QUEST = os.path.join(PLUGIN, "src", "scripts", "quest", "main.py")  # quest 입구(세션 PATH에 싣지 않는다 — 스킬·훅이 전체 경로로 부른다)
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from quest.libs import config, presets, rules  # noqa: E402
from quest.libs.context import Context  # noqa: E402


def _real_git_first():
    """macOS의 `/usr/bin/git`은 부를 때마다 xcrun을 거치는 껍데기라 진짜 git보다 두 배쯤 느리다(시험은 git을 수천 번 부른다).
    이 시험 프로세스(와 자식)에서만 진짜 git 자리를 PATH 앞에 둔다. 찾지 못하면 그대로 둔다 — 판정은 같고 빠르기만 다르다."""
    if sys.platform != "darwin" or shutil.which("git") != "/usr/bin/git":
        return
    try:
        out = subprocess.run(["xcrun", "--find", "git"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return
    found = out.stdout.strip()
    if out.returncode == 0 and os.path.isabs(found) and os.access(found, os.X_OK):
        os.environ["PATH"] = os.path.dirname(found) + os.pathsep + os.environ.get("PATH", "")


_real_git_first()

SVC_RULE_DOCS = {
    "patterns": [r"(?:^|/)\.agents/rules/.+\.md$", r"^svc/bootstrap/\.agents/rules/"],
    "optional_prefix": "svc/", "search_dirs": [],
}
SVC = {
    "branches": {"integration": "dev/main"},
    "quest": {"quests": "svc/.agents/workflow/quests", "rule_docs": SVC_RULE_DOCS},
    "session": {"terminal": "none"},
}


def svc(rule_docs=SVC_RULE_DOCS):
    """SVC 사본 — rule_docs가 None이면 `quest.rule_docs`를 빼서 "바뀐 규칙 문장" 확인을 끈다."""
    data = json.loads(json.dumps(SVC))
    if rule_docs is None:
        del data["quest"]["rule_docs"]
    else:
        data["quest"]["rule_docs"] = rule_docs
    return data


# 시험 프로세스 안의 규칙 사본 — 이름: (규칙 모듈의 자리 상수, 내용)
SVC_RULES = {
    "tests": ("TESTS_FILE", {
        "patterns": [r"(?:^|/)src/(?:test|testFixtures)/", r"(?:^|/)test_[^/]*\.py$"],
    }),
}
PLUGIN_FILES = {"flow": rules.FLOW_FILE, "files": rules.FILES_FILE, "git": rules.GIT_FILE, "tests": rules.TESTS_FILE,
                "terminals": presets.TERMINALS_FILE}  # 플러그인 정본 자리(바꾸기 전)
ATTR = {"flow": "FLOW_FILE", "files": "FILES_FILE", "git": "GIT_FILE", "tests": "TESTS_FILE",
        "terminals": "TERMINALS_FILE"}
MODULE = {"terminals": presets}  # 자리 상수를 가진 모듈 — 적지 않은 것은 rules(규칙), terminals는 presets(프리셋)

_RULES_DIR = tempfile.mkdtemp()
atexit.register(shutil.rmtree, _RULES_DIR, True)
for _name, (_attr, _data) in SVC_RULES.items():
    _path = os.path.join(_RULES_DIR, f"{_name}.json")
    with open(_path, "w", encoding="utf-8") as _f:
        json.dump(_data, _f, ensure_ascii=False)
    setattr(rules, _attr, _path)


def plugin_rules(name):
    """플러그인 정본 규칙 파일의 내용(사전)."""
    with open(PLUGIN_FILES[name], encoding="utf-8") as f:
        return json.load(f)


def use_rules(case, name, **values):
    """이 시험 동안만 규칙 `name`(files·git·tests·terminals)을 바꾼다 — 지금 쓰는 사본(없으면 플러그인 정본) 위에 values를 덮는다."""
    module = MODULE.get(name, rules)
    current = getattr(module, ATTR[name])
    with open(current, encoding="utf-8") as f:
        data = json.load(f)
    data.update(values)
    d = tempfile.mkdtemp()
    case.addCleanup(shutil.rmtree, d, True)
    path = os.path.join(d, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    p = mock.patch.object(module, ATTR[name], path)
    p.start()
    case.addCleanup(p.stop)
    return path


def write(root, data=None):
    """root에 `.satchel/quest.json`을 쓴다(기본은 SVC)."""
    path = config.config_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(SVC if data is None else data, f, ensure_ascii=False, indent=2)
    return path


def make(data=None, root=None):
    """파일 없이 Config 하나."""
    return config.build(SVC if data is None else data, root)


def context(root, data=None):
    """root의 문맥 — 설정 파일 없이 시험 설정(기본 SVC)으로."""
    return Context(root, make(data, root))
