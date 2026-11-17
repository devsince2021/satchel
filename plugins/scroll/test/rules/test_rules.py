"""규칙 파일 시험 — src/rules/flow.json·files.json·git.json·tests.json 읽기(quest/libs/rules): 정본 값, 깨진 파일 오류, 바꾸면 판정이 따라 바뀜."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test import helpers as testing
from quest.commands import status as status_cmd
from quest.libs import bash, commits, rules
from quest.libs.checks import tdd
from quest.libs.context import Context
from quest.libs import rules


WORK = "Q-061"


TEST_FILE = "svc/src/test/java/ATest.java"


MAIN_FILE = "svc/src/main/java/A.java"


PLAN = "# 계획\n\n## 할 일\n\n- [x] 1. 하나 — 시험 `test_a`\n\n## 구현하며 바뀐 것\n\n- 없음\n"


def flow_data():
    with open(rules.FLOW_FILE, encoding="utf-8") as f:
        return json.load(f)


def rename_step(data, old, new):
    """단계 이름 하나를 모든 자리(steps·order·reviews)에서 바꾼 사본."""
    text = json.dumps(data, ensure_ascii=False)
    return json.loads(text.replace(f'"{old}"', f'"{new}"'))


def shipped(name, cls):
    return cls(testing.plugin_rules(name), testing.PLUGIN_FILES[name])


class FlowFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.n = 0

    def write(self, data=None, raw=None):
        self.n += 1
        path = os.path.join(self.tmp, f"flow-{self.n}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(data, ensure_ascii=False))
        return path

    def assertRuleError(self, path, words):
        with self.assertRaises(rules.RuleError) as e:
            rules.load(path)
        self.assertIn(path, str(e.exception))
        self.assertIn(words, str(e.exception))

    def test_shipped_file_loads(self):
        flow = rules.load(rules.FLOW_FILE)
        self.assertEqual(flow.names, ("req", "plan", "plan-review", "test", "run", "review", "fix", "done", "merge"))
        self.assertEqual(flow.required, ("req", "plan", "plan-review", "run", "review", "done"))
        self.assertEqual(flow.todo_steps, ("test", "run"))
        self.assertEqual(flow.merge_step, "merge")

    def test_broken_json(self):
        self.assertRuleError(self.write(raw='{"steps": ['), "JSON이 깨졌다")

    def test_missing_file(self):
        self.assertRuleError(os.path.join(self.tmp, "없음.json"), "읽지 못했다")

    def test_chain_prerequisites(self):
        """단계 사슬: 앞으로 거슬러 처음 만나는 필수 단계, 단계의 `start_after`가 있으면 그것 — 표는 flow.json에서만."""
        flow = rules.load(rules.FLOW_FILE)
        self.assertEqual(flow.chain_rule, "previous_required")
        got = {n: flow.prerequisite(n) for n in flow.names}
        self.assertEqual(got, {"req": None, "plan": "req", "plan-review": "plan", "test": "plan", "run": "plan-review",
                               "review": "run", "fix": "review", "done": "review", "merge": "done"})
        data = flow_data()
        for s in data["steps"]:
            s.pop("start_after", None)
        self.assertEqual(rules.load(self.write(data)).prerequisite("test"), "plan-review")  # 덮지 않으면 규칙 그대로

    def test_chain_bad_values(self):
        data = flow_data()
        data["chain"]["needs"] = "아무거나"
        self.assertRuleError(self.write(data), "chain.needs")
        data = flow_data()
        del data["chain"]
        self.assertRuleError(self.write(data), "`chain`이 없다")
        data = flow_data()
        next(s for s in data["steps"] if s["name"] == "test")["start_after"] = "review"
        self.assertRuleError(self.write(data), "start_after")
        data = flow_data()
        next(s for s in data["steps"] if s["name"] == "test")["start_after"] = "없는단계"
        self.assertRuleError(self.write(data), "start_after")

    def test_missing_required_key(self):
        data = flow_data()
        del data["order"]["todo_first"]
        self.assertRuleError(self.write(data), "`todo_first`이 없다")
        data = flow_data()
        del data["steps"][0]["required"]
        self.assertRuleError(self.write(data), "steps[0]에 `required`이 없다")

    def test_unknown_step_reference(self):
        data = flow_data()
        data["order"]["todo_first"]["then"] = "impl"
        self.assertRuleError(self.write(data), "'impl'가 steps에 없다")

    def test_bad_values(self):
        data = flow_data()
        data["steps"][1]["by"] = "누군가"
        self.assertRuleError(self.write(data), "steps[1].by")
        data = flow_data()
        data["steps"].append(dict(data["steps"][0]))
        self.assertRuleError(self.write(data), "두 번 있다")
        data = flow_data()
        data["commit"]["todo_ref"]["pattern"] = "#("
        self.assertRuleError(self.write(data), "정규식이 아니다")
        data = flow_data()
        data["steps"][0]["뜻"] = "x"
        self.assertRuleError(self.write(data), "모르는 키")

    def test_merge_stages(self):
        """합치기 단계(`merge`)는 check·deliver·cleanup 차례, 칸은 name·stage·does·takes, takes는 설정 키 꼴."""
        flow = rules.load(rules.FLOW_FILE)
        self.assertEqual([m["name"] for m in flow.merge], ["check", "deliver", "cleanup"])
        self.assertEqual([m["takes"] for m in flow.merge], [[], ["deliver.verify"], []])
        self.assertEqual(flow.merge_stage("deliver"), "② deliver")
        data = flow_data()
        data["merge"].reverse()
        self.assertRuleError(self.write(data), "merge는 단계 ['check', 'deliver', 'cleanup']")
        data = flow_data()
        data["merge"][1]["takes"] = ["verify"]
        self.assertRuleError(self.write(data), "merge[1].takes는 설정 키")
        data = flow_data()
        data["merge"][0]["after"] = "x"
        self.assertRuleError(self.write(data), "merge[0]에 모르는 키")
        data = flow_data()
        data["push"] = []
        self.assertRuleError(self.write(data), "뿌리에 모르는 키: ['push']")

    def test_status_stops_with_rule_error(self):
        broken = self.write(raw="[]")
        old = rules.FLOW_FILE
        rules.FLOW_FILE = broken
        self.addCleanup(setattr, rules, "FLOW_FILE", old)
        out = io.StringIO()
        with redirect_stdout(out):
            code = status_cmd.main([WORK], ctx=Context(self.tmp, testing.make()))
        self.assertEqual(code, 2)
        self.assertIn("quest_check: 규칙 오류: 규칙 파일", out.getvalue())


class FlowDrivesJudgmentTest(unittest.TestCase):
    """flow.json 사본의 단계를 바꾸면 단계 찾기·빠진 단계·차례 판정이 따라 바뀐다."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.git("init", "-q")
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"),
                     ("gc.auto", "0"), ("maintenance.auto", "false")):
            self.git("config", k, v)
        self.ctx = Context(self.tmp, testing.make())
        folder = os.path.join(self.tmp, testing.SVC["quest"]["quests"], f"{WORK}-sample")
        os.makedirs(folder)
        with open(os.path.join(folder, "plan.md"), "w", encoding="utf-8") as f:
            f.write(PLAN)
        self.commit(f"{WORK} req: 요구사항")
        self.commit(f"{WORK} plan: 결정")
        self.commit(f"{WORK} plan-review: 검토")
        self.commit(f"{WORK} test: #1 시험", TEST_FILE)
        self.commit(f"{WORK} impl: #1 구현", MAIN_FILE)
        self.old = rules.FLOW_FILE
        self.addCleanup(setattr, rules, "FLOW_FILE", self.old)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.tmp, *args], capture_output=True, text=True, check=True).stdout

    def commit(self, title, rel=None):
        if rel:
            path = os.path.join(self.tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write("x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", title)

    def use(self, data):
        path = os.path.join(self.tmp, f"flow-{self._testMethodName}.json")  # 커밋을 다 쌓은 뒤에 쓴다(판정에 안 든다)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        rules.FLOW_FILE = path

    def test_shipped_rules_do_not_know_impl(self):
        steps = [s for s, _ in commits.steps_of(self.ctx, WORK)]
        self.assertEqual(steps, ["req", "plan", "plan-review", "test"])
        self.assertIn("run", commits.missing(commits.steps_of(self.ctx, WORK)))
        self.assertIn(f"할 일 1: 구현 커밋 `{WORK} run: #1 …`이 없다", tdd.tdd_problems(self.ctx, WORK, PLAN))

    def test_renamed_step_is_followed(self):
        self.use(rename_step(flow_data(), "run", "impl"))
        steps = [s for s, _ in commits.steps_of(self.ctx, WORK)]
        self.assertEqual(steps, ["req", "plan", "plan-review", "test", "impl"])
        self.assertEqual(commits.missing(commits.steps_of(self.ctx, WORK)), ["review", "done"])
        self.assertEqual(tdd.tdd_problems(self.ctx, WORK, PLAN), [])

    def test_required_flag_is_followed(self):
        data = rename_step(flow_data(), "run", "impl")
        next(s for s in data["steps"] if s["name"] == "fix")["required"] = True
        self.use(data)
        self.assertEqual(commits.missing(commits.steps_of(self.ctx, WORK)), ["review", "fix", "done"])


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def bad(self, cls, data, words):
        path = os.path.join(self.tmp, "x.json")
        with self.assertRaises(rules.RuleError) as e:
            cls(data, path)
        self.assertIn(path, str(e.exception))
        self.assertIn(words, str(e.exception))


class ShippedTest(Files):
    """플러그인 정본 값 — 옛 설정 기본값 그대로."""

    def test_files(self):
        f = shipped("files", rules.Files)
        self.assertEqual(f.paths, [".satchel/**", ".claude/settings.json", ".claude/hooks/**", ".claude/skills/**",
                                   "AGENTS.md", "CLAUDE.md"])

    def test_git(self):
        """막는 git 명령 하나의 목록에서 두 수단을 만든다 — settings deny 앞머리는 옛 deny_bash와 같은 차례·같은 값,
        guard 목록은 옛 block_git(merge·pull·rebase·am)을 다 품고 deny에만 있던 명령까지 넓힌다."""
        g = shipped("git", rules.Git)
        self.assertEqual([c.command for c in g.commands],
                         ["push", "checkout", "restore", "reset", "stash", "clean", "switch", "merge", "pull", "rebase", "am"])
        self.assertTrue(all(c.why for c in g.commands))
        self.assertEqual(g.deny_bash, ["git push", "git checkout", "git restore", "git reset --hard", "git stash", "git clean",
                                       "git switch", "git merge", "git pull", "git rebase", "git am"])
        self.assertEqual(g.block_git, ["push", "checkout", "restore", "stash", "clean", "switch", "merge", "pull", "rebase", "am"])
        self.assertEqual(g.block_git_args, ["reset:--hard"])

    def test_tests(self):
        t = shipped("tests", rules.Tests)
        for path in ("tests/test_a.py", "test/a.py", "src/test/java/A.java", "a/src/testFixtures/F.java", "a/__tests__/x.js",
                     "spec/models/a_spec.rb", "pkg/x_test.go", "lib/a_test.rb", "web/a.spec.ts", "web/a.test.tsx", "web/b.test.mjs",
                     "src/test_x.py", "app/src/main/java/FooTest.java", "app/FooTests.java", "app/BarTest.kt", "x/BazSpec.scala"):
            self.assertTrue(t.is_test_file(path), path)
        for path in ("src/main/A.java", "README.md", "latest/x.py", "contest/a.py", "src/Testing.java", "web/test.ts",
                     "src/test-helpers.ts", "app/Contest.java"):
            self.assertFalse(t.is_test_file(path), path)

    def test_load_all(self):
        with mock.patch.multiple(rules, **{testing.ATTR[n]: p for n, p in testing.PLUGIN_FILES.items() if n != "terminals"}):
            flow, files, git, tests = rules.load_all()
        self.assertEqual(flow.merge_step, "merge")


class BrokenTest(Files):
    def test_files(self):
        ok = testing.plugin_rules("files")
        self.bad(rules.Files, {**ok, "extra": 1}, "모르는 키: ['extra']")
        self.bad(rules.Files, {}, "['paths']이 없다")
        self.bad(rules.Files, {**ok, "paths": "AGENTS.md"}, "paths는 비지 않은 글 목록")
        self.bad(rules.Files, {**ok, "deny_paths": ok["paths"]}, "모르는 키: ['deny_paths']")  # 옛 이름은 받지 않는다

    def test_git(self):
        ok = testing.plugin_rules("git")
        one = {"command": "merge", "why": "합치기는 리드 몫"}
        self.bad(rules.Git, {**ok, "extra": 1}, "모르는 키: ['extra']")
        self.bad(rules.Git, {}, "['commands']이 없다")
        for old in ("deny_bash", "block_git", "block_git_args"):  # 나누기 전(0.10.0) 막기 목록 파일의 키는 받지 않는다
            self.bad(rules.Git, {**ok, old: []}, f"모르는 키: ['{old}']")
        self.bad(rules.Git, {"commands": "merge"}, "commands는 목록")
        self.bad(rules.Git, {"commands": ["merge"]}, "commands[0]은 JSON 객체")
        self.bad(rules.Git, {"commands": [{"why": "x"}]}, "commands[0]에 ['command']이 없다")
        self.bad(rules.Git, {"commands": [{"command": "merge"}]}, "commands[0]에 ['why']이 없다")
        self.bad(rules.Git, {"commands": [{**one, "sub": 1}]}, "commands[0]의 모르는 키: ['sub']")
        for name in ("", "Merge", "git merge", "merge --x", 3):
            self.bad(rules.Git, {"commands": [{**one, "command": name}]}, "commands[0].command는 git 하위 명령 이름")
        self.bad(rules.Git, {"commands": [{**one, "why": ""}]}, "commands[0].why는 비지 않은 글")
        self.bad(rules.Git, {"commands": [one, {**one, "args": ["--x"]}]}, "commands[1]: merge가 두 번 적혔다")
        for args in ([], "--hard", [""], ["a b"], ["a:b"], [3]):
            self.bad(rules.Git, {"commands": [{**one, "command": "reset", "args": args}]}, "commands[0].args는")
        g = rules.Git({"commands": [one, {"command": "commit", "args": ["--amend", "-e"], "why": "x"}]}, "x")
        self.assertEqual((g.deny_bash, g.block_git, g.block_git_args),
                         (["git merge", "git commit --amend", "git commit -e"], ["merge"], ["commit:--amend", "commit:-e"]))
        self.assertEqual(rules.Git({"commands": []}, "x").deny_bash, [])

    def test_tests(self):
        ok = testing.plugin_rules("tests")
        self.bad(rules.Tests, {**ok, "patterns": ["("]}, "정규식이 아니다")
        self.bad(rules.Tests, {**ok, "areas": {}}, "모르는 키: ['areas']")
        self.bad(rules.Tests, {**ok, "companions": []}, "모르는 키: ['companions']")


class FollowsFileTest(Files):
    """규칙 파일을 바꾸면 판정이 따라 바뀐다 — 값이 코드가 아니라 파일에서 온다."""

    def test_tests_file(self):
        testing.use_rules(self, "tests", patterns=[r"(?:^|/)spec/"])
        t = rules.tests()
        self.assertTrue(t.is_test_file("a/spec/x.rb"))
        self.assertFalse(t.is_test_file("src/test/java/A.java"))

    def test_git_file(self):
        testing.use_rules(self, "git", commands=[{"command": "stash", "why": "x"}])
        self.assertEqual((rules.git().deny_bash, rules.git().block_git), (["git stash"], ["stash"]))

    def test_files_file(self):
        testing.use_rules(self, "files", paths=["x/**"])
        self.assertEqual(rules.files().paths, ["x/**"])

    def test_broken_file_is_rule_error(self):
        for name, attr, read in (("files", "FILES_FILE", rules.files), ("git", "GIT_FILE", rules.git)):
            path = os.path.join(self.tmp, f"{name}.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{")
            with mock.patch.object(rules, attr, path):
                with self.assertRaises(rules.RuleError) as e:
                    read()
            self.assertIn("JSON이 깨졌다", str(e.exception))


class GitBlockTest(unittest.TestCase):
    """정본 git.json으로 만든 두 수단이 실제로 막는 범위 — 나누기 전(0.10.0 막기 목록 파일의 deny_bash·block_git)보다 줄지 않고,
    작업 세션이 정당하게 쓰는 git 명령은 둘 다 지나간다."""
    OLD_DENY = ["git push", "git checkout", "git restore", "git reset --hard", "git stash", "git clean",
                "git switch", "git merge", "git pull", "git rebase", "git am"]
    OLD_GUARD = ["merge", "pull", "rebase", "am"]
    WORK = ("git add -A", "git add a.py", "git commit -m 'Q-1 run: #1 checkout 고침'", "git status", "git status --short",
            "git diff", "git diff --stat HEAD~1", "git log --oneline -5", "git log --merges", "git show HEAD",
            "git show HEAD:reset.md", "git rev-parse HEAD", "git ls-files", "git branch --show-current", "git merge-base a b",
            "git grep -n push", "git reset --soft HEAD~1", "git reset HEAD -- a.py", "git -C /w status", "git blame a.py",
            "echo git push", "grep -n 'git stash' README.md")

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.git = shipped("git", rules.Git)

    def gate(self, cmd):
        return bash.gate_reason(cmd, self.tmp, tuple(self.git.block_git), block_git_arg=tuple(self.git.block_git_args))

    @staticmethod
    def denied(cmd, prefixes):
        """settings deny `Bash(<앞머리>:*)` 꼴 — 명령이 그 앞머리로 시작하면 걸린다."""
        return any(cmd == p or cmd.startswith(p + " ") for p in prefixes)

    def test_deny_not_narrowed(self):
        for old in self.OLD_DENY:
            self.assertIn(old, self.git.deny_bash)
            self.assertTrue(self.denied(old + " x", self.git.deny_bash), old)

    def test_guard_not_narrowed(self):
        for sub in self.OLD_GUARD:
            for cmd in (f"git {sub} x", f"git -C /w {sub} x", f"sh -c 'git {sub} x'", f"find . -exec git {sub} x \\;"):
                self.assertTrue(self.gate(cmd), cmd)

    def test_guard_widened_to_deny_only_commands(self):
        """deny에만 있던 명령도 guard가 풀어 읽어 막는다(-C 뒤·sh -c·find -exec 안 — deny 앞머리로는 못 잡던 꼴)."""
        for cmd in ("git -C /w push", "sh -c 'git checkout main'", "find . -exec git restore a \\;", "eval git stash",
                    "git -C /w clean -fd", "bash -c 'git switch x'", "git -C /w reset --hard HEAD", "echo $(git reset --hard)"):
            self.assertTrue(self.gate(cmd), cmd)
            self.assertFalse(self.denied(cmd, self.git.deny_bash), cmd)

    def test_work_commands_pass_both(self):
        for cmd in self.WORK:
            self.assertIsNone(self.gate(cmd), cmd)
            self.assertFalse(self.denied(cmd, self.git.deny_bash), cmd)


if __name__ == "__main__":
    unittest.main()
