"""deliver 설정 — 설정 파일(`.studio/tailoring.json`, 읽기는 공용 `libs/settings.py`)에서 `branches`·`deliver` 묶음만 요청한다.
꼭 있어야 하는 키는 `branches.integration` 하나. 다른 묶음의 값은 읽지 않지만 파일 전체의 모르는 키는 멈춘다."""
from libs import settings

GROUPS = ("branches", "deliver")
NEEDS = ("branches.integration",)
ConfigError = settings.ConfigError


def load(root):
    """root(저장소 뿌리)의 {"branches.integration": …, "deliver.verify": …}. 틀리면 ConfigError."""
    values, _ = settings.values(settings.read(root), GROUPS, NEEDS, root)
    return values
