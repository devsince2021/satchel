"""작업 세션 가르기 — 훅 입력의 `cwd`가 작업 세션인지, 그 세션의 기록(`session.json`)은 무엇인지.

작업 세션 = `cwd` 저장소의 브랜치가 작업 브랜치(고정 꼴 `quest/<ID>-<슬러그>`)이고, 그 작업의 세션 기록
(`<git 공통 자리>/satchel/quest-sessions/<ID>/session.json`, `quest open`이 남긴다)이 있고 기록의 워크트리가 이 저장소 꼭대기인 것.
그 밖(리드 세션·통합 브랜치·다른 저장소·git 밖·기록 없음·합친 뒤 `done/`)은 None — 훅은 아무것도 하지 않는다.
작업 브랜치인지는 설정을 읽기 전에 가른다(설정 없는 저장소에서 말없이 지나가게). 작업 브랜치에서 설정 오류(`ConfigError`,
필수 키 없음 포함)는 그대로 올린다(부른 쪽이 판정 불가로 지나가며 한 줄을 남긴다).
"""
import json
import os

from quest.libs.context import Context, branch_work

RECORD = "session.json"


def record_path(ctx, work):
    """이 작업의 세션 기록 파일 — 없으면 None. 기록 자리는 git 공통 자리라 리드 체크아웃과 작업 워크트리에서 같다."""
    path = os.path.join(ctx.cfg.records_dir(ctx.root), work, RECORD)
    return path if os.path.isfile(path) else None


def load_record(path):
    with open(path, encoding="utf-8") as f:
        found = json.load(f)
    if not isinstance(found, dict):
        raise ValueError(f"세션 기록이 사전이 아니다: {path}")
    return found


def work_session(cwd):
    """(ctx, work, record) — 작업 세션이 아니면 None."""
    if not cwd or branch_work(cwd) is None:
        return None
    ctx = Context.from_cwd(cwd)
    if ctx is None:
        return None
    work = ctx.current_work(cwd)
    if work is None:
        return None
    path = record_path(ctx, work)
    if path is None:
        return None
    record = load_record(path)
    if os.path.realpath(record.get("worktree") or "") != ctx.root:
        return None
    return ctx, work, record
