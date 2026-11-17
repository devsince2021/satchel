"""quest/libs/gitcommit.py 시험 — `git commit` 명령에서 제목 읽기, 읽을 수 없는 꼴, 작업 세션 제목 판정."""
import os
import shutil
import subprocess
import tempfile
import unittest

from test import helpers as testing  # noqa: F401  src를 import 길에
from quest.libs import commits, gitcommit


def titles(cmd, cwd="/w"):
    return [(c.title, c.unreadable is not None, c.amend_keep) for c in gitcommit.commits(cmd, cwd)]


class ReadTest(unittest.TestCase):
    def test_message_shapes(self):
        for cmd in ('git commit -m "Q-001 plan: 결정"', "git commit -qm 'Q-001 plan: 결정'", "git commit -am 'Q-001 plan: 결정'",
                    "git commit -m'Q-001 plan: 결정'", "git commit --message='Q-001 plan: 결정'", "git commit --message 'Q-001 plan: 결정'",
                    "git commit --mess 'Q-001 plan: 결정'", "git commit -m 'Q-001 plan: 결정' -m '본문'",
                    "git commit -m 'Q-001 plan: 결정\n\n본문 줄'", "git commit -m '\nQ-001 plan: 결정'", "git -C /w commit --allow-empty -m 'Q-001 plan: 결정'",
                    "git add -A && git commit -m 'Q-001 plan: 결정'", "env X=1 git commit -m 'Q-001 plan: 결정'",
                    "sh -c \"git commit -m 'Q-001 plan: 결정'\"", "eval git commit -m \\'Q-001 plan: 결정\\'"):
            with self.subTest(cmd=cmd):
                self.assertEqual(titles(cmd), [("Q-001 plan: 결정", False, False)])

    def test_cat_heredoc_message(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nQ-001 run: #1 구현\n\n본문 줄\nEOF\n)\""
        self.assertEqual(titles(cmd), [("Q-001 run: #1 구현", False, False)])

    def test_unreadable_shapes(self):
        for cmd in ("git commit", "git commit -a", "git commit -F msg.txt", "git commit --file=msg.txt", "git commit -C HEAD",
                    "git commit -c HEAD", "git commit --reuse-message=HEAD", "git commit --fixup=HEAD", "git commit --squash HEAD",
                    "git commit -e -m 'Q-001 plan: x'", "git commit --amend", "git commit -t tpl", "git commit -m \"$X\"",
                    "git commit -m \"$(date) x\""):
            with self.subTest(cmd=cmd):
                found = titles(cmd)
                self.assertEqual(len(found), 1, cmd)
                self.assertTrue(found[0][1], cmd)

    def test_amend_no_edit_keeps_head_title(self):
        self.assertEqual(titles("git commit --amend --no-edit"), [(None, False, True)])
        self.assertEqual(titles("git commit --amend -m 'Q-001 fix: x'"), [("Q-001 fix: x", False, False)])

    def test_not_commits(self):
        for cmd in ("git status", "echo git commit -m x", "git log --grep commit", "git commit-tree x", "grep commit a.txt"):
            with self.subTest(cmd=cmd):
                self.assertEqual(titles(cmd), [])


class WorkProblemTest(unittest.TestCase):
    def judge(self, cmd):
        return [gitcommit.work_problem("Q-001", c) for c in gitcommit.commits(cmd, "/w")]

    def test_good_titles_pass(self):
        for title in ("Q-001 plan: 결정", "Q-001 plan-review: x", "Q-001 test: #1 a", "Q-001 run: #1 #2 a", "Q-001 review: x",
                      "Q-001 fix: x", "Q-001 done: x", "Q-002·Q-001 done: 묶음"):
            with self.subTest(title=title):
                self.assertEqual(self.judge(f"git commit -m '{title}'"), [None])

    def test_bad_titles_block_with_shape(self):
        cases = {"고침": "Q-001 <단계>", "Q-002 plan: 남의 작업": "Q-001 <단계>", "Q-001 planning: x": "plan·plan-review",
                 "Q-001 req: 요구사항": "리드", "Q-001 merge: x": "부명령 merge", "Q-001 run: 번호 없음": "#N"}
        for title, want in cases.items():
            with self.subTest(title=title):
                found = self.judge(f"git commit -m '{title}'")[0]
                self.assertIsNotNone(found, title)
                self.assertIn(want, found)

    def test_unreadable_blocks_and_tells_m(self):
        for cmd in ("git commit", "git commit -F m.txt", "git commit -e -m 'Q-001 plan: x'"):
            with self.subTest(cmd=cmd):
                found = self.judge(cmd)[0]
                self.assertIn("읽을 수 없다", found)
                self.assertIn("-m", found)

    def test_title_judge_is_shared_with_end(self):
        """커밋 때 판정과 끝 확인은 같은 판정 코드(`commits.title_problem`·`Flow.todo_missing`)를 쓴다."""
        self.assertIsNone(commits.title_problem("Q-001", "Q-001 run: #3 x", "작업 세션"))
        self.assertIn("#N", commits.title_problem("Q-001", "Q-001 run: x", "작업 세션"))


class AmendKeepTest(unittest.TestCase):
    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        for args in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
                     ("config", "commit.gpgsign", "false")):
            subprocess.run(["git", "-C", self.repo, *args], check=True)

    def commit(self, title):
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "--allow-empty", "-m", title], check=True)

    def test_amend_no_edit_judges_head_title(self):
        self.commit("Q-001 plan: 결정")
        c = gitcommit.commits("git commit --amend --no-edit", self.repo)[0]
        self.assertIsNone(gitcommit.work_problem("Q-001", c))
        self.commit("아무 제목")
        c = gitcommit.commits("git commit --amend --no-edit", self.repo)[0]
        self.assertIn("꼴이", gitcommit.work_problem("Q-001", c))


if __name__ == "__main__":
    unittest.main()
