"""작업 세션의 단계 기록 — 시작 명령(`seam step`)이 쓰고 커밋 때 확인(PreToolUse 훅 `guard` — `gitcommit.work_problem`)이 읽는다.

자리는 세션 기록 자리(`<git 공통 자리>/studio/seam-sessions/<ID>/steps.json` — 작업 세션 deny라 손으로 못 고친다).
꼴: {"current": 지금 단계, "started": [시작 명령으로 들어온 단계, 처음 들어온 차례], "log": [{"step", "at"}]}.
파일이 없으면 아무 단계도 시작하지 않은 것이다. 깨졌으면 ValueError — 부르는 쪽이 막는다(기록이 없다고 지나가는 길을 두지 않는다).
"""
import json
import os
from datetime import datetime

STEPS_FILE = "steps.json"


def read_steps(session_dir):
    path = os.path.join(session_dir, STEPS_FILE)
    if not os.path.exists(path):
        return {"current": None, "started": [], "log": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("started"), list):
        raise ValueError(f"단계 기록이 깨졌다: {path}")
    return data


def record_start(session_dir, step):
    """지금 단계를 `step`으로, 시작한 단계 목록에 더한다(이미 있으면 차례는 그대로). 임시 파일 뒤 바꿔 넣기."""
    data = read_steps(session_dir)
    data["current"] = step
    if step not in data["started"]:
        data["started"].append(step)
    data.setdefault("log", []).append({"step": step, "at": datetime.now().isoformat(timespec="seconds")})
    tmp = os.path.join(session_dir, STEPS_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(session_dir, STEPS_FILE))
    return data
