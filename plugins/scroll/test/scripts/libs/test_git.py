"""libs/git.py 시험 — git 부르기(실패는 GitError), 짧은 해시 한 길이, 저장소 뿌리, 지금 브랜치, git 공통 자리, 리베이스 중인지."""
import os
import subprocess
import tempfile
import unittest

from libs import git as gitlib


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout


class GitTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.realpath(tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
            git(self.repo, "config", k, v)
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base")

    def test_short_hash_one_length(self):
        """짧은 해시는 한 자리(`short`)에서 한 길이(`SHORT` = 7, `git log --oneline` 기본과 같게)로 만든다."""
        full = gitlib.run(self.repo, "rev-parse", "HEAD").strip()
        self.assertEqual(gitlib.SHORT, 7)
        self.assertEqual(gitlib.short(full), full[:7])
        self.assertEqual(gitlib.short_head(self.repo), full[:7])

    def test_run_and_error(self):
        self.assertEqual(gitlib.run(self.repo, "log", "-1", "--format=%s").strip(), "base")
        with self.assertRaises(gitlib.GitError) as e:
            gitlib.run(self.repo, "rev-parse", "--verify", "nope")
        self.assertTrue(str(e.exception).startswith("git rev-parse 실패: "))

    def test_root_branch_and_outside(self):
        sub = os.path.join(self.repo, "a", "b")
        os.makedirs(sub)
        self.assertEqual(gitlib.project_root(sub), self.repo)
        self.assertEqual(gitlib.current_branch(sub), "main")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.assertIsNone(gitlib.project_root(outside.name))
        self.assertEqual(gitlib.current_branch(outside.name), "")
        with self.assertRaises(gitlib.GitError):
            gitlib.common_dir(outside.name)

    def test_common_dir_is_shared_by_worktrees(self):
        wt = self.repo + "-wt"
        git(self.repo, "worktree", "add", "-q", "-b", "x", wt)
        self.addCleanup(subprocess.run, ["git", "-C", self.repo, "worktree", "remove", wt], capture_output=True)
        self.assertEqual(gitlib.common_dir(wt), os.path.join(self.repo, ".git"))
        self.assertEqual(gitlib.common_dir(self.repo), os.path.join(self.repo, ".git"))

    def test_rebasing(self):
        self.assertFalse(gitlib.rebasing(self.repo))
        with open(os.path.join(self.repo, "a.txt"), "w", encoding="utf-8") as f:
            f.write("main\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "main a")
        git(self.repo, "checkout", "-q", "-b", "side", "HEAD~1")
        with open(os.path.join(self.repo, "a.txt"), "w", encoding="utf-8") as f:
            f.write("side\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "side a")
        subprocess.run(["git", "-C", self.repo, "rebase", "main"], capture_output=True)
        self.assertTrue(gitlib.rebasing(self.repo))
        git(self.repo, "rebase", "--abort")
        self.assertFalse(gitlib.rebasing(self.repo))


if __name__ == "__main__":
    unittest.main()
