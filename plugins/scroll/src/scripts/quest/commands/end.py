"""부명령 `end` — 끝 확인. 읽기만 한다. 작업 저장소(또는 작업 워크트리) 안에서 부른다.

  <quest> end <ID>   # 통과 0, 빠진 것이 있으면 1(목록), 잘못 부름·git 실패·설정 오류 2

차례: 문맥·규칙 읽기 → 끝 확인 항목(`quest/libs/checks/`) → 막는 줄·경고 줄 → 마지막 줄 `quest_check: 통과`/`막힘`.
"""
from quest.libs import checks
from quest.libs.context import GitError, for_work


def main(argv, ctx=None):
    found = for_work("end", argv, ctx)
    if isinstance(found, int):
        return found
    ctx, work = found
    try:
        problems = checks.end_problems(ctx, work)
        warned = checks.end_warnings(ctx, work)
    except GitError as e:
        print(f"quest_check: {e}")
        return 2
    for line in problems:
        print(f"- {line}")
    for line in warned:
        print(f"- 경고: {line}")
    print("quest_check: " + ("막힘" if problems else "통과"))
    return 1 if problems else 0
