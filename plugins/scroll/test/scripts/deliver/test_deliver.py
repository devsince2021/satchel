"""deliver 시험 — quest merge ② 단계가 쓰는 안쪽 부품(src/scripts/deliver/steps.py·config.py)을 함수로 부른다: 검사 없음·통과·실패, 리베이스 충돌,
확인에서 멈춤, 설정(`branches.integration`만 필수, 옛 키 멈춤), 부르는 방향. 사람·세션이 deliver를 직접 부르는 입구는 없다."""
import ast
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from deliver import config, steps
from test import helpers as testing


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout.strip()


class Repo(unittest.TestCase):
    """통합 브랜치 `main`, 일반 브랜치 `feature/x`(quest 기록·세션 없음). 설정은 `branches`(+ 시험마다 `deliver`)만."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.top = os.path.join(self.tmp, "repo")
        os.makedirs(self.top)
        git(self.top, "init", "-q", "-b", "main")
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"), ("gc.auto", "0")):
            git(self.top, "config", k, v)
        self.put(self.top, "a.txt", "a\n")
        self.set_config({"branches": {"integration": "main"}})
        git(self.top, "branch", "feature/x")
        self.wt = None

    def put(self, root, name, text):
        with open(os.path.join(root, name), "w", encoding="utf-8") as f:
            f.write(text)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"{name}")

    def set_config(self, data):
        os.makedirs(os.path.join(self.top, ".satchel"), exist_ok=True)
        with open(os.path.join(self.top, ".satchel", "quest.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        git(self.top, "add", "-A")
        git(self.top, "commit", "-q", "-m", "설정")

    def checkout_feature(self):
        self.wt = os.path.join(self.tmp, "repo-x")
        git(self.top, "worktree", "add", "-q", self.wt, "feature/x")
        return self.wt

    def deliver(self, branch, dry_run=False):
        """quest merge가 하듯 설정을 읽고 deliver 단계를 부른다 → (0 넣음·1 멈춤·2 설정 오류, 단계 출력, 멈춘 까닭)."""
        said = []
        try:
            values = config.load(self.top)
        except config.ConfigError as e:
            return 2, "", f"설정 오류: {e}"
        integration, verify = values["branches.integration"], values["deliver.verify"]
        if dry_run:
            return 0, "\n".join(steps.plan_lines(self.top, branch, integration, verify)), ""
        try:
            steps.deliver(self.top, branch, integration, verify, say=said.append)
        except steps.Stop as e:
            return 1, "\n".join(said), f"{e.stage}에서 멈춤 — {e.reason}"
        return 0, "\n".join(said), ""

    def subject(self, ref="main"):
        return git(self.top, "log", "-1", "--format=%s", ref)


class DeliverTest(Repo):
    def test_no_verify_uses_temp_worktree_and_fast_forwards(self):
        """브랜치를 체크아웃한 워크트리가 없으면 임시 워크트리에서 리베이스하고, 합친 뒤 지운다. 검사가 비면 건너뛴다."""
        git(self.top, "checkout", "-q", "feature/x")
        self.put(self.top, "b.txt", "b\n")
        git(self.top, "checkout", "-q", "main")
        self.put(self.top, "c.txt", "c\n")
        code, out, err = self.deliver("feature/x")
        self.assertEqual(code, 0, err)
        self.assertIn("임시 워크트리", out)
        self.assertIn("deliver 검사: 설정 deliver.verify가 비어 건너뜀", out)
        self.assertIn("병합: feature/x → main", out)
        self.assertEqual(git(self.top, "log", "--format=%s", "-3", "main").splitlines(), ["b.txt", "c.txt", "설정"])
        self.assertEqual(git(self.top, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertFalse(os.path.exists(os.path.join(git(self.top, "rev-parse", "--git-common-dir"), "satchel", "deliver", "feature-x")))

    def test_verify_passes_in_checked_out_worktree(self):
        self.set_config({"branches": {"integration": "main"}, "deliver": {"verify": "test -f b.txt && test \"$(pwd -P)\" = \"$WT\""}})
        wt = self.checkout_feature()
        self.put(wt, "b.txt", "b\n")
        with mock.patch.dict(os.environ, {"WT": wt}):
            code, out, err = self.deliver("feature/x")
        self.assertEqual(code, 0, err)
        self.assertIn("deliver 검사: test -f b.txt", out)
        self.assertEqual(self.subject(), "b.txt")

    def test_verify_failure_stops_before_merge(self):
        self.set_config({"branches": {"integration": "main"}, "deliver": {"verify": "echo 빨강; exit 3"}})
        wt = self.checkout_feature()
        self.put(wt, "b.txt", "b\n")
        code, _, err = self.deliver("feature/x")
        self.assertEqual(code, 1)
        self.assertIn("검사에서 멈춤 — 합치기 전 검사 실패(종료 3): echo 빨강; exit 3", err)
        self.assertIn("빨강", err)
        self.assertEqual(self.subject(), "설정")

    def test_rebase_conflict_stops(self):
        wt = self.checkout_feature()
        self.put(wt, "a.txt", "브랜치\n")
        self.put(self.top, "a.txt", "통합\n")
        code, _, err = self.deliver("feature/x")
        self.assertEqual(code, 1)
        self.assertIn("리베이스에서 멈춤 — 리베이스가 부딪혔다.", err)
        self.assertEqual(self.subject(), "a.txt")
        code, _, err = self.deliver("feature/x")  # 풀지 않고 다시 부르면 확인에서 멈춘다
        self.assertEqual(code, 1)
        self.assertIn("확인에서 멈춤", err)
        git(wt, "rebase", "--abort")

    def test_rebase_conflict_in_temp_worktree_is_undone(self):
        git(self.top, "checkout", "-q", "feature/x")
        self.put(self.top, "a.txt", "브랜치\n")
        git(self.top, "checkout", "-q", "main")
        self.put(self.top, "a.txt", "통합\n")
        code, _, err = self.deliver("feature/x")
        self.assertEqual(code, 1)
        self.assertIn("리베이스가 부딪혀 되돌렸다", err)
        self.assertEqual(git(self.top, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(self.subject("feature/x"), "a.txt")

    def test_checks_before_anything(self):
        code, _, err = self.deliver("main")
        self.assertEqual((code, "통합 브랜치 main 자체다" in err), (1, True))
        code, _, err = self.deliver("nope")
        self.assertIn("브랜치가 없다: nope", err)
        git(self.top, "checkout", "-q", "-b", "other")
        code, _, err = self.deliver("feature/x")
        self.assertEqual(code, 1)
        self.assertIn("확인에서 멈춤 — 지금 체크아웃이 main가 아니다", err)
        git(self.top, "checkout", "-q", "main")
        wt = self.checkout_feature()
        with open(os.path.join(wt, "new.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        code, _, err = self.deliver("feature/x")
        self.assertIn("커밋 안 한 변경", err)
        self.assertIn("?? new.txt", err)

    def test_dry_run_lines(self):
        code, out, _ = self.deliver("feature/x", dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("rebase main", out)
        self.assertIn("merge --ff-only feature/x", out)
        self.assertEqual(self.subject(), "설정")


class ConfigTest(Repo):
    def test_only_integration_is_required(self):
        """quest 묶음·session.terminal 없이 돈다(위 시험들). 통합 브랜치가 없으면 그것만 적으라고 멈춘다."""
        self.set_config({"deliver": {"verify": ""}})
        code, _, err = self.deliver("feature/x")
        self.assertEqual(code, 2)
        self.assertIn("설정에 branches.integration을 적어라", err)
        self.assertNotIn("session.terminal", err)

    def test_old_merge_verify_key_stops(self):
        self.set_config({"branches": {"integration": "main"}, "merge": {"verify": "make"}})
        code, _, err = self.deliver("feature/x")
        self.assertEqual(code, 2)
        self.assertIn("모르는 키: merge.verify — deliver.verify로 옮겼다", err)


class ImportDirectionTest(unittest.TestCase):
    """부르는 방향 — deliver는 quest를 모르고, 공용 libs는 quest·deliver를 모르고, quest/libs는 commands를 모른다."""

    def imports(self, folder):
        found = {}
        for dirpath, _, files in os.walk(os.path.join(testing.SRC, folder)):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as f:
                        tree = ast.parse(f.read())
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom) and node.module:
                            found.setdefault(node.module.split(".")[0], set()).add(os.path.relpath(path, testing.SRC))
                            if node.module.startswith("quest.commands"):
                                found.setdefault("quest.commands", set()).add(os.path.relpath(path, testing.SRC))
                        elif isinstance(node, ast.Import):
                            for a in node.names:
                                found.setdefault(a.name.split(".")[0], set()).add(os.path.relpath(path, testing.SRC))
        return found

    def test_directions(self):
        self.assertNotIn("quest", self.imports("deliver"))
        shared = self.imports("libs")
        self.assertNotIn("quest", shared)
        self.assertNotIn("deliver", shared)
        self.assertNotIn("quest.commands", self.imports(os.path.join("quest", "libs")))


if __name__ == "__main__":
    unittest.main()
