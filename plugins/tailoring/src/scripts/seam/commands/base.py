"""부명령 `base` — 작업 범위 기준 커밋(검토 범위 `<base>..HEAD`). 읽기만 한다.

  <seam> base <ID>

차례: 문맥·규칙 읽기 → 기준 커밋 셈(`seam/libs/commits.py`의 `work_base`) → 찍기. 0, 잘못 부름·git 실패·설정 오류 2.
"""
from seam.libs import commits
from seam.libs.context import GitError, for_work


def main(argv, ctx=None):
    found = for_work("base", argv, ctx)
    if isinstance(found, int):
        return found
    ctx, work = found
    try:
        print(commits.work_base(ctx, work))
    except GitError as e:
        print(f"seam_check: {e}")
        return 2
    return 0
