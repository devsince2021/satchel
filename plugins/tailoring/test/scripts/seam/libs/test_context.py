"""seam/libs/context.py 시험 — 판정 대상 저장소·설정·작업 브랜치·기록 폴더."""
import os
import subprocess
import tempfile
import unittest

from test import helpers as testing
from seam.libs.context import Context


BRANCH = "piece/P-077-sample-work"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.realpath(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", BRANCH, self.repo], check=True)
        testing.write(self.repo)
        self.ctx = Context(self.repo)
        self.pieces = os.path.join(self.repo, "svc", ".agents", "workflow", "pieces")

    def test_current_work_from_branch(self):
        self.assertEqual(self.ctx.current_work(self.repo), "P-077")
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "dev/main"], check=True)
        self.assertIsNone(self.ctx.current_work(self.repo))

    def test_from_cwd_finds_git_top_and_config(self):
        os.makedirs(self.pieces)
        found = Context.from_cwd(self.pieces)
        self.assertEqual(found.root, self.repo)
        self.assertEqual(found.cfg.integration, "dev/main")
        self.assertIsNone(Context.from_cwd(None))
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.assertIsNone(Context.from_cwd(outside.name))  # git 밖이면 문맥이 없다

    def test_piece_dir_follows_config(self):
        self.assertIsNone(self.ctx.piece_dir("P-078"))
        put(os.path.join(self.repo, ".agents", "pieces", "P-078-x", "requirements.md"), "기본 자리\n")
        self.assertIsNone(self.ctx.piece_dir("P-078"))  # 설정의 기록 폴더만 본다
        put(os.path.join(self.pieces, "P-078-sample", "requirements.md"), "- 작업: P-078 · 흐름: seam\n")
        self.assertTrue(self.ctx.piece_dir("P-078").endswith("svc/.agents/workflow/pieces/P-078-sample"))

    def test_contexts_do_not_share_state(self):
        """전역 상태가 없다 — 두 저장소의 문맥이 서로의 뿌리·설정을 바꾸지 않는다."""
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        testing.write(other.name, {"branches": {"integration": "main"}, "session": {"terminal": "none"}})
        second = Context(other.name)
        self.assertEqual(second.cfg.integration, "main")
        self.assertEqual(self.ctx.root, self.repo)
        self.assertEqual(self.ctx.cfg.integration, "dev/main")

    def test_git_error(self):
        from seam.libs.context import GitError
        with self.assertRaises(GitError):
            self.ctx.git("rev-parse", "--verify", "없는-가지")


if __name__ == "__main__":
    unittest.main()
