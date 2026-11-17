"""git 부르기·저장소 뿌리 찾기·짧은 해시 — quest·deliver가 같이 쓴다. Python 3.9 표준 라이브러리만."""
import os
import subprocess


SHORT = 7  # 짧은 해시 길이 — 출력·기록에 찍는 해시는 모두 이 길이(`git log --oneline` 기본과 같게). 만드는 자리는 `short` 한 곳


class GitError(Exception):
    pass


def short(sha):
    """짧은 해시 — 모든 출력·기록이 이것으로 줄인다(길이 `SHORT`)."""
    return sha[:SHORT]


def short_head(cwd):
    """cwd HEAD의 짧은 해시."""
    return short(run(cwd, "rev-parse", "HEAD").strip())


def run(cwd, *args, timeout=None):
    """cwd에서 git — 표준 출력. 부를 수 없음·시간 초과·종료 코드 0 아님은 GitError(`git <하위> 실패: …`)."""
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git {args[0]} 실패: {e}") from e
    if out.returncode != 0:
        raise GitError(f"git {args[0]} 실패: {out.stderr.strip()}")
    return out.stdout


def project_root(cwd):
    """cwd가 든 git 작업본 꼭대기(심볼릭 링크를 푼 실제 경로). git 밖이면 None."""
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    except OSError:
        return None
    top = out.stdout.strip()
    return os.path.realpath(top) if out.returncode == 0 and top else None


def current_branch(cwd):
    """cwd의 지금 브랜치 이름. 떨어진 HEAD·git 밖은 빈 글."""
    try:
        out = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True)
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def common_dir(cwd):
    """git 공통 자리(워크트리끼리 같은 `.git`)의 실제 경로. 못 찾으면 GitError."""
    out = subprocess.run(["git", "-C", cwd, "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    common = out.stdout.strip()
    if out.returncode != 0 or not common:
        raise GitError(f"git 공통 자리를 못 찾음: {cwd}")
    if not os.path.isabs(common):
        common = os.path.join(cwd, common)
    return os.path.realpath(common)


def rebasing(cwd):
    """cwd 작업본에서 리베이스가 진행 중인가."""
    git_dir = run(cwd, "rev-parse", "--absolute-git-dir").strip()
    return any(os.path.exists(os.path.join(git_dir, d)) for d in ("rebase-merge", "rebase-apply"))
