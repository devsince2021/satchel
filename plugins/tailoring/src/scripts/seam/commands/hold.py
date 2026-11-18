"""부명령 `hold` — 작업 세션이 멈추려 할 때 되돌리기(Stop 훅). 플러그인 훅(`src/hooks/hooks.json`)이 모든 세션의 Stop마다 부른다.

차례: 표준 입력의 훅 입력(JSON) 읽기 → 판정(`seam/libs/stop.py`의 `verdict` — 작업 브랜치에서만, 되돌림 횟수 포함) → 되돌리면
종료 2와 stderr 한 문단, 아니면 0. 입력이 깨졌으면 판정 불가로 0과 stderr 한 줄.
"""
import json
import sys

from seam.libs import stop


def main(argv=()):
    """stdin의 훅 입력(JSON)을 판정한다. 인자는 받지 않는다."""
    try:
        payload = json.load(sys.stdin)
    except Exception as e:  # noqa: BLE001  입력이 깨졌으면 판정 불가로 통과, 한 줄만 남긴다
        sys.stderr.write(f"[stop_wait] 판정 불가로 통과: {type(e).__name__}: {e}\n")
        return 0
    found = stop.verdict(payload)
    if found is None:
        return 0
    sys.stderr.write(found)
    return 2
