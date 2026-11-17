"""부명령 `status` — 커밋 제목으로 찾은 단계와 첫 시각, 빠진 필수 단계(알림만). 읽기만 한다.

  <quest> status <ID>

차례: 문맥·규칙 읽기 → 단계 찾기(`quest/libs/commits.py`) → 단계마다 한 줄 → 빠진 단계 한 줄. 0, 잘못 부름·git 실패·설정 오류 2.
"""
from quest.libs import commits
from quest.libs.context import GitError, for_work


def main(argv, ctx=None):
    found = for_work("status", argv, ctx)
    if isinstance(found, int):
        return found
    ctx, work = found
    try:
        steps = commits.steps_of(ctx, work)
    except GitError as e:
        print(f"quest_check: {e}")
        return 2
    for s, t in steps:
        print(f"{s}\t{t}")
    gone = commits.missing(steps)
    print("빠진 단계: " + (", ".join(gone) if gone else "없음"))
    return 0
