"""판정 대상 저장소의 문맥 — 저장소 뿌리(root)와 그 seam 설정(cfg)을 한 번 만들어 넘긴다.

전역 상태를 두지 않는다. 부명령은 시작할 때 `Context.from_cwd(…)` 또는 `Context(root)`로 하나 만들고
그 객체를 인자로 넘긴다. 시험은 저장소마다 새 문맥을 만든다. git 부르기·뿌리 찾기는 공용 `libs/git.py`.
"""
import glob
import os

from libs import git as gitlib
from libs.git import GitError  # noqa: F401  부르는 쪽이 이 모듈에서 함께 쓴다
from seam.libs import config, rules


def branch_work(cwd):
    """cwd 브랜치가 작업 브랜치(고정 꼴 `piece/<ID>-<슬러그>`)면 작업 ID, 아니면(git 밖 포함) None.
    설정을 읽지 않는다 — 훅이 설정 없는 저장소·리드 세션에서 말없이 지나가게 이것으로 먼저 가른다."""
    return config.work_from_branch(gitlib.current_branch(cwd))


class Context:
    """저장소 뿌리(`root`, git 밖이면 None)와 그 설정(`cfg`)."""

    def __init__(self, root, cfg=None):
        self.root = os.path.realpath(root) if root else None
        self.cfg = cfg if cfg is not None else config.load(self.root)

    @classmethod
    def from_cwd(cls, cwd):
        """cwd가 든 git 작업본 꼭대기의 문맥. cwd가 없거나 git 밖이면 None. 설정이 틀리거나 필수 키가 없으면 ConfigError."""
        found = gitlib.project_root(cwd) if cwd else None
        return cls(found) if found else None

    def git(self, *args):
        """저장소 뿌리에서 git — 표준 출력. 실패·시간 초과(10초)는 GitError."""
        return gitlib.run(self.root, *args, timeout=10)

    def current_work(self, cwd):
        """cwd 브랜치가 작업 브랜치(고정 꼴 `piece/<ID>-<슬러그>`)면 작업 ID, 아니면 None."""
        return branch_work(cwd)

    def piece_dir(self, work):
        """기록 폴더 `<설정 seam.pieces>/<ID>-<슬러그>/`. 없으면 None."""
        if self.root is None:
            return None
        hits = sorted(d for d in glob.glob(os.path.join(self.root, self.cfg.rel("pieces"), f"{work}-*")) if os.path.isdir(d))
        return hits[0] if hits else None

    def requirements_template(self):
        return self.cfg.requirements_template(self.root)


def for_work(name, argv, ctx=None):
    """작업 ID 하나를 받는 읽기 부명령(`status`·`inspect`·`base`)의 앞머리 — (문맥, 작업 ID) 또는 종료 코드 2(까닭을 찍은 뒤).
    ctx가 없으면 지금 자리가 든 git 작업본의 문맥을 만들고, 규칙 파일이 깨졌으면 판정 전에 멈춘다."""
    try:
        if ctx is None:
            ctx = Context.from_cwd(os.getcwd())
            if ctx is None:
                print("seam_check: git 작업본 안에서 부른다")
                return 2
        rules.load_all()
    except config.ConfigError as e:
        print(f"seam_check: 설정 오류: {e}")
        return 2
    except rules.RuleError as e:
        print(f"seam_check: 규칙 오류: {e}")
        return 2
    if len(argv) != 1 or not ctx.cfg.is_id(argv[0]):
        print(f"쓰는 법: python3 {config.ENTRY} {name} {ctx.cfg.id_shape}")
        return 2
    return ctx, argv[0]
