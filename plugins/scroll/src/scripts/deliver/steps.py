"""deliver 단계 — 브랜치 하나를 통합 브랜치에 넣는다. 지금 체크아웃(통합 브랜치)에서 부른다.

차례(`STAGES`):
1. 확인 — 지금 체크아웃이 통합 브랜치이고 커밋 안 한 변경이 없음, 브랜치가 있고 통합 브랜치가 아님, 브랜치 워크트리
   (주어진 자리 → 그 브랜치를 체크아웃한 워크트리 → 없으면 임시 워크트리 `<git 공통 자리>/satchel/deliver/<브랜치>`)가
   그 브랜치이고 리베이스 중이 아니고 깨끗함.
2. 리베이스 — 워크트리에서 `git rebase <통합 브랜치>`. 부딪히면 멈춘다(임시 워크트리면 되돌리고 지운다).
3. 검사 — 설정 `deliver.verify`를 워크트리에서 셸로(종료 0이어야 한다). 비면 건너뛴다.
4. 합치기 전 — 부르는 쪽이 준 `before_merge(워크트리)`(없으면 건너뜀). 까닭 글을 돌려주면 멈춘다. 커밋을 더해도 된다.
5. 합치기 — 지금 체크아웃에서 `git merge --ff-only <브랜치>`.
멈추면 `Stop(단계, 까닭)`. 한 단계는 다시 해도 같다 — 고치고 다시 부른다. 푸시·브랜치 지우기는 하지 않는다.
"""
import os
import re
import subprocess

from libs import git as gitlib

STAGES = ("확인", "리베이스", "검사", "합치기 전", "합치기")
VERIFY_TIMEOUT = 3600
TEMP_IN_GIT = ("satchel", "deliver")  # 임시 워크트리 자리 — <git 공통 자리>/satchel/deliver/<브랜치>


class Stop(Exception):
    """단계(`stage`)에서 멈춤 — 까닭(`reason`)."""

    def __init__(self, stage, reason):
        super().__init__(reason)
        self.stage, self.reason = stage, reason


def _git(cwd, *args, stage):
    try:
        return gitlib.run(cwd, *args).strip()
    except gitlib.GitError as e:
        raise Stop(stage, str(e)) from e


def checked_out(here, branch):
    """branch를 체크아웃한 워크트리 자리(실제 경로). 없으면 None."""
    path = None
    for line in _git(here, "worktree", "list", "--porcelain", stage="확인").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}" and path:
            return os.path.realpath(path)
    return None


def temp_place(here, branch):
    return os.path.join(gitlib.common_dir(here), *TEMP_IN_GIT, re.sub(r"[^A-Za-z0-9._-]", "-", branch))


def verify_problem(worktree, command):
    """프로젝트 검사(`deliver.verify`)를 워크트리에서 돌린다. 통과(또는 명령 없음)면 None, 아니면 까닭."""
    if not command:
        return None
    try:
        out = subprocess.run(["sh", "-c", command], cwd=worktree, capture_output=True, text=True, errors="replace",
                             timeout=VERIFY_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"합치기 전 검사 시간 초과({VERIFY_TIMEOUT}초): {command}. 다시 부르거나 브랜치를 고친다."
    except OSError as e:
        return f"합치기 전 검사를 부르지 못했다: {e}"
    if out.returncode != 0:
        tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-15:])
        return f"합치기 전 검사 실패(종료 {out.returncode}): {command}. 브랜치를 고친 뒤 다시 부른다:\n{tail}"
    return None


def plan_lines(here, branch, integration, verify, worktree=None, before_merge_lines=()):
    """`--dry-run`이 찍는 차례."""
    wt = worktree or "<브랜치 워크트리 — 체크아웃한 자리, 없으면 임시>"
    return [f"확인: git -C {here} branch --show-current == {integration}, 커밋 안 한 변경 없음",
            f"확인: git -C {wt} branch --show-current == {branch}, 리베이스 중 아님, status 비어 있음",
            f"리베이스: git -C {wt} rebase {integration}",
            (f"검사: 합치기 전 검사(워크트리에서): {verify}  (종료 0)" if verify else "검사: 설정 deliver.verify가 비어 건너뜀"),
            *[f"합치기 전: {line}" for line in before_merge_lines],
            f"합치기: git -C {here} merge --ff-only {branch}"]


def _check_here(here, branch, integration):
    if branch == integration:
        raise Stop("확인", f"넣을 브랜치가 통합 브랜치 {integration} 자체다.")
    if _git(here, "branch", "--show-current", stage="확인") != integration:
        raise Stop("확인", f"지금 체크아웃이 {integration}가 아니다 — 통합 브랜치 체크아웃(리드 체크아웃)에서 부른다.")
    if _git(here, "status", "--porcelain", "--untracked-files=no", stage="확인"):
        raise Stop("확인", "지금 체크아웃(리드 체크아웃)에 커밋 안 한 변경이 있다.")
    try:
        gitlib.run(here, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    except gitlib.GitError as e:
        raise Stop("확인", f"브랜치가 없다: {branch}") from e


def _check_worktree(wt, branch):
    if not os.path.isdir(wt):
        raise Stop("확인", f"워크트리가 없다: {wt}")
    if _git(wt, "branch", "--show-current", stage="확인") != branch:
        raise Stop("확인", f"워크트리 브랜치가 {branch}가 아니다(리베이스 중일 수 있다): {wt}")
    if gitlib.rebasing(wt):
        raise Stop("확인", f"워크트리에서 리베이스가 진행 중이다. {wt}에서 풀고 git rebase --continue 뒤 다시 부른다.")
    dirty = _git(wt, "status", "--porcelain", stage="확인")
    if dirty:
        raise Stop("확인", f"워크트리({wt})에 커밋 안 한 변경이 있다. 커밋을 마쳤는지 본다"
                         "(만든 파일이 남은 것이면 프로젝트 .gitignore에 넣거나 지운다):\n" + dirty)


def deliver(here, branch, integration, verify="", worktree=None, before_merge=None, say=print):
    """branch를 integration에 넣는다(차례는 머리글). 넣은 뒤 통합 브랜치 머리(짧은 해시). 멈추면 Stop."""
    _check_here(here, branch, integration)
    temp = None
    if worktree is None:
        worktree = checked_out(here, branch)
    if worktree is None:
        temp = temp_place(here, branch)
        if os.path.exists(temp):
            raise Stop("확인", f"임시 워크트리 자리가 남아 있다: {temp} — `git -C {here} worktree remove {temp}` 뒤 다시 부른다.")
        _git(here, "worktree", "add", "--quiet", temp, branch, stage="확인")
        worktree = temp
        say(f"deliver 확인: {branch}를 체크아웃한 워크트리가 없어 임시 워크트리 {temp}에서 한다")
    try:
        _check_worktree(worktree, branch)
        try:
            gitlib.run(worktree, "rebase", integration)
        except gitlib.GitError as e:
            if temp:
                gitlib.run(worktree, "rebase", "--abort")
                raise Stop("리베이스", f"리베이스가 부딪혀 되돌렸다. {branch}를 체크아웃해 git rebase {integration}로 풀고 다시 부른다.\n{e}") from e
            raise Stop("리베이스", f"리베이스가 부딪혔다. {worktree}에서 풀고(git rebase --continue) 다시 부른다.\n{e}") from e
        say(f"deliver 리베이스: {branch} → {integration} 위로")
        problem = verify_problem(worktree, verify)
        if problem:
            raise Stop("검사", problem)
        say(f"deliver 검사: {verify} 통과" if verify else "deliver 검사: 설정 deliver.verify가 비어 건너뜀")
        if before_merge:
            problem = before_merge(worktree)
            if problem:
                raise Stop("합치기 전", problem)
        _git(here, "merge", "--ff-only", branch, stage="합치기")
        head = gitlib.short(_git(here, "rev-parse", "HEAD", stage="합치기"))
        say(f"병합: {branch} → {integration} {head}")
        return head
    finally:
        if temp and os.path.isdir(temp):
            try:
                gitlib.run(here, "worktree", "remove", temp)
            except gitlib.GitError as e:
                say(f"경고: 임시 워크트리를 지우지 못했다({temp}): {e}")
