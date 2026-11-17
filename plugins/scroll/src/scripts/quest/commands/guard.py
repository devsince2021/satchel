"""부명령 `guard` — 작업 세션의 도구 호출 직전 막기(PreToolUse 훅). 플러그인 훅(`src/hooks/hooks.json`)이 이 플러그인이 켜진 모든 세션의
`Bash`·`Agent`·`Task`·`AskUserQuestion` 호출마다 부른다. 표준 입력: 훅 입력 JSON.

차례: 훅 입력 읽기 → 작업 세션 가르기(`quest/libs/session.py` — 작업 브랜치 + 세션 기록) → 판정(`quest/libs/block.py`) → 막으면 종료 2와
stderr 한 문단. 작업 세션인지 가를 수 없음(입력 깨짐·작업 브랜치의 설정 오류(필수 키 없음 포함)·기록 깨짐)은 0과 stderr 한 줄.
작업 세션이 아니면(리드 세션) quest 설정(`.satchel/quest.json`)이 있는 저장소의 Bash `git commit`만 본다(`block.lead_judge` — 작업 ID로
시작하는 제목의 꼴·리드 단계, 요구사항 파일을 새로 더하는 커밋의 ID). 그 밖은 말없이 0, 판정 예외(설정 오류 등)는 0과 stderr 한 줄.
"""
import json
import os
import sys

from quest.libs import block, session


def main(argv=(), stdin=None, deny_rules=None):
    """stdin의 훅 입력(JSON)을 판정한다. 인자는 받지 않는다."""
    try:
        payload = json.load(stdin or sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") not in block.JUDGED:
            return 0
        found_session = session.work_session(payload.get("cwd") or os.getcwd())
        lead = block.lead_judge(payload) if found_session is None else None  # 리드 세션 — `git commit`만
    except Exception as e:  # noqa: BLE001  작업 세션인지·리드 커밋을 가를 수 없으면 판정 불가로 통과
        sys.stderr.write(f"[pre_tool] 판정 불가로 통과: {type(e).__name__}: {e}\n")
        return 0
    found = lead if found_session is None else block.judge(payload, found_session, deny_rules)
    if not found:
        return 0
    sys.stderr.write(f"[pre_tool] {found}\n")
    return 2
