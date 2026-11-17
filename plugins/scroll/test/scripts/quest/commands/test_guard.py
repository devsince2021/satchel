"""quest/commands/guard.py·quest/libs/block.py 시험 — 질문 창·하위 에이전트 머리말·세션 기록 값으로 부르는 Bash 판정."""
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test import helpers as testing
from quest.libs import block as pt
from quest.commands import guard as guard_cmd
from quest.libs import session
from libs import settings


WF = "svc/.agents/workflow"


REQ = ("# t\n\n- 작업: Q-077 · 결정 번호: 0771~0780 · 브랜치: quest/Q-077-sample · 흐름: quest\n"
       "- 날짜: 2026-11-12 · 요청: 사용자 · 대상: guard\n- 출발: 시험\n\n"
       "## 문제\n\n- 어긋남\n\n## 요구\n\n- R1. 하나\n\n## 범위\n\n- 안: x\n\n## 수용 기준\n\n- 시험 OK\n")


README = "# 작업\n\n## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n| Q-077 | t | 진행 | 0771~0780 |\n"


GLOB_DOTDOT = "cat $P/domain/src/main/java/*/../ -h; find …; grep …"  # 하위 에이전트가 확인 창에 멈추던 꼴


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout


class WorkSession(unittest.TestCase):
    """임시 리드 체크아웃 `<tmp>/lead`(dev/main)에서 Q-077 작업 세션을 연다 — 워크트리 `<tmp>/lead-q-077`."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")  # 작업 세션 홈 — 진짜 홈 settings를 읽지 않게
        os.makedirs(self.home)
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.home})
        env.start()
        self.addCleanup(env.stop)
        self.lead = os.path.join(self.tmp, "lead")
        put(os.path.join(self.lead, WF, "quests", "Q-077-sample", "requirements.md"), REQ)
        put(os.path.join(self.lead, WF, "quests", "README.md"), README)
        put(os.path.join(self.lead, "README.md"), "# r\n")
        put(os.path.join(self.lead, ".gitignore"), "__pycache__/\n")
        testing.write(self.lead, copy.deepcopy(testing.SVC))
        git(self.lead, "init", "-q", "-b", "dev/main")
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"), ("gc.auto", "0"), ("maintenance.auto", "false")):
            git(self.lead, "config", k, v)
        git(self.lead, "add", "-A")
        git(self.lead, "commit", "-q", "-m", "Q-077 req: 요구사항")
        out = subprocess.run([sys.executable, testing.QUEST, "open", "Q-077", "--lead", "lead-session"], cwd=self.lead,
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.wt = os.path.join(self.tmp, "lead-q-077")
        found = session.work_session(self.wt)
        self.assertIsNotNone(found)
        self.record = found[2]

    def run_hook(self, tool, cwd=None, deny_rules=None, **inp):
        err = io.StringIO()
        payload = {"tool_name": tool, "tool_input": inp, "cwd": cwd or self.wt}
        with mock.patch("sys.stderr", err):
            code = guard_cmd.main(stdin=io.StringIO(json.dumps(payload)), deny_rules=deny_rules)
        return code, err.getvalue()

    def bash(self, command, cwd=None, deny_rules=None):
        return self.run_hook("Bash", cwd=cwd, deny_rules=deny_rules, command=command)

    def start(self, *steps):
        """단계를 시작 명령으로 들어온 것으로 세션 기록에 남긴다(사슬 확인 없이 — `quest step`의 기록 함수)."""
        from quest.commands import step as step_cmd
        for name in steps:
            step_cmd.record_start(self.record["session_dir"], name)

    def commit(self, *titles):
        for title in titles:
            git(self.wt, "commit", "-q", "--allow-empty", "-m", title)


class AgentAskTest(WorkSession):
    """Agent·AskUserQuestion — 작업 세션에서만."""

    def setUp(self):
        super().setUp()
        self.header = pt.header_marker()
        self.good = self.header + "\n- 자리: /w 안만 읽고 고친다.\n\n할 일: x"

    def test_header_comes_from_plugin_file(self):
        self.assertEqual(self.header, "[공용 머리말 — quest]")
        self.assertEqual(pt.placeholders(), ["{GUIDE_DOCS}", "{REPORT}", "{SCOPE}", "{SCRATCHPAD}", "{WORKTREE}"])

    def test_ask_user_blocked(self):
        code, err = self.run_hook("AskUserQuestion", questions=[{"question": "?"}])
        self.assertEqual(code, 2)
        self.assertIn("결정 요청", err)
        self.assertIn("대기: 리드", err)
        self.assertIn("[<작업 ID> → <리드>] 결정 요청", err)

    def test_agent_without_header_is_blocked(self):
        code, err = self.run_hook("Agent", prompt="할 일: Task 4만 해라")
        self.assertEqual(code, 2)
        self.assertIn(pt.HEADER, err)  # 플러그인 머리말 파일의 절대 경로
        self.assertEqual(self.run_hook("Task", prompt="할 일: x")[0], 2)

    def test_agent_with_leftover_placeholder_is_blocked(self):
        for left in pt.placeholders():
            with self.subTest(left=left):
                code, err = self.run_hook("Agent", prompt=self.header + f"\n- 자리: {left} 안만\n할 일: x")
                self.assertEqual(code, 2)
                self.assertIn(left, err)

    def test_agent_with_header_or_read_line_passes(self):
        self.assertEqual(self.run_hook("Agent", prompt=self.good)[0], 0)
        self.assertEqual(self.run_hook("Agent", prompt="먼저 `/p/skills/quest/subagent-header.md`를 읽고 따르라. 할 일: x")[0], 0)

    def test_other_header_is_blocked(self):
        self.assertEqual(self.run_hook("Agent", prompt="[공용 머리말 — other 작업 세션]\n할 일: x")[0], 2)

    def test_block_suggested_read_line_passes(self):
        """막는 글이 권하는 "먼저 `<경로>`를 읽고 따르라" 줄은 그대로 넣으면 통과한다."""
        err = self.run_hook("Agent", prompt="할 일: x")[1]
        line = re.search(r"먼저 `[^`]+`를 읽고 따르라", err)
        self.assertIsNotNone(line, err)
        self.assertEqual(self.run_hook("Agent", prompt=line.group(0) + ". 할 일: x")[0], 0)
        self.assertEqual(self.run_hook("Agent", prompt="먼저 `x/other.md`를 읽고 따르라. 할 일: x")[0], 2)

    def test_agent_judge_exception_passes_with_one_line(self):
        with mock.patch.object(pt, "agent_problem", side_effect=TypeError("boom")):
            code, err = self.run_hook("Agent", prompt="x")
        self.assertEqual(code, 0)
        self.assertEqual(1, len(err.strip().splitlines()))
        self.assertIn("TypeError", err)

    def test_other_tools_and_broken_input_pass(self):
        self.assertEqual(self.run_hook("Read", file_path="/x")[0], 0)
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(guard_cmd.main(stdin=io.StringIO("not json")), 0)
            self.assertEqual(guard_cmd.main(stdin=io.StringIO("[]")), 0)

    def test_session_check_error_passes_with_one_line(self):
        """작업 세션인지 가를 수 없으면(설정 오류 등) 판정 불가로 0과 한 줄."""
        with mock.patch.object(session, "work_session", side_effect=ValueError("깨짐")):
            code, err = self.run_hook("AskUserQuestion", questions=[])
        self.assertEqual(code, 0)
        self.assertIn("판정 불가로 통과", err)


class BashTest(WorkSession):
    """Bash — 세션 기록의 리드 저장소·켜는 깃발·세션 settings deny로 판정한다."""

    def test_git_reverting_and_lead_writes_blocked(self):
        for cmd in (f"git -C {self.wt} reset --hard", "git reset --hard HEAD~1", "git checkout x", "git stash",
                    f"git -C {self.lead} commit -m x", f"cd {self.lead} && git commit -m x",
                    "python3 -c 'import subprocess; subprocess.run([\"git\", \"checkout\", \"x\"])'",
                    "echo ${f%/*}"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd)[0], 2, cmd)

    def test_block_git_from_record(self):
        for cmd in ("git -C /w merge x", "sh -c 'git pull'", "git rebase dev/main"):
            code, err = self.bash(cmd)
            self.assertEqual(code, 2, cmd)
            self.assertIn("[막힘]", err)

    def test_block_git_args_from_record(self):
        rec = os.path.join(self.record["session_dir"], "session.json")
        with open(rec, encoding="utf-8") as f:
            data = json.load(f)
        data["block_git_args"] = ["commit:--amend"]
        put(rec, json.dumps(data))
        self.assertEqual(self.bash("git commit --amend")[0], 2)
        self.start("plan")
        self.assertEqual(self.bash("git commit -m 'Q-077 plan: x'")[0], 0)
        data["block_git_args"] = ["commit"]  # 꼴이 틀리면 모두 막는다
        put(rec, json.dumps(data))
        code, err = self.bash("git status")
        self.assertEqual(code, 2)
        self.assertIn("<하위>:<인자>", err)

    def test_session_settings_deny_writes(self):
        """세션 settings deny(규칙 `src/rules/files.json`·세션 기록 자리·리드 체크아웃)에 걸리는 Bash 쓰기."""
        for cmd in ("echo x > .satchel/quest.json", f"echo x > {self.wt}/.satchel/quest.json", "cp /tmp/a AGENTS.md",
                    f"echo x >> {self.record['session_dir']}/task.md", f"touch {self.lead}/x",
                    "python3 -c \"open('.satchel/quest.json', 'w').write('{}')\"",
                    f"echo '| C-001 |' >> {WF}/quests/carryover.md", f"sed -i '' s/a/b/ {self.wt}/{WF}/quests/carryover.md"):
            with self.subTest(cmd=cmd):
                code, err = self.bash(cmd)
                self.assertEqual(code, 2, cmd)
        self.assertIn("편집을 막은 경로", self.bash("echo x > .satchel/quest.json")[1])
        self.assertIn("리드에게", self.bash("echo x > .satchel/quest.json")[1])

    def test_normal_commands_pass(self):
        self.start("plan")
        for cmd in ("git status", "git log --oneline -3", "git add -A && git commit -qm 'Q-077 plan: m'", "git diff --stat HEAD~1",
                    f"python3 {testing.QUEST} status Q-077", "python3 -m unittest discover -s tests",
                    "echo x > notes.md", f"echo x > {self.wt}/src/a.py", "mkdir -p src && touch src/b.py",
                    f"echo '- [x] 끝' >> {self.record['orders']}", f"cat {self.lead}/README.md", "ls"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), (0, ""), cmd)

    def test_glob_then_dotdot_blocked(self):
        code, err = self.bash(GLOB_DOTDOT)
        self.assertEqual(code, 2, err)
        self.assertIn("glob 없이", err)
        self.assertIn("$P/domain/src/main/java/*/../", err)
        self.assertEqual(self.bash("grep -rn '*/../' . && ls ../*")[0], 0)

    def test_deny_reads(self):
        rules = [f"Read(/{self.wt}/secret/**)", f"Read(/{self.wt}/**/.env)"]
        for cmd in ("cat secret/x", "git show HEAD:secret/x", f"cat {self.wt}/.env", "tail -n 1 sub/.env"):
            code, err = self.bash(cmd, deny_rules=rules)
            self.assertEqual(code, 2, cmd)
            self.assertIn("읽기를 막은 경로", err)
            self.assertIn("리드에게", err)
        put(os.path.join(self.wt, "s.sh"), f"#!/bin/sh\ncat {self.wt}/secret/x\n")
        self.assertEqual(self.bash("bash s.sh", deny_rules=rules)[0], 2)  # 스크립트 파일 본문

    def test_deny_rules_from_record_settings_and_home(self):
        """deny는 세션 settings(세션 기록 `settings`)와 `CLAUDE_CONFIG_DIR`의 settings.json·settings.local.json에서."""
        rules = pt.load_deny_rules(self.record["settings"], self.record["home"])
        self.assertIn("AskUserQuestion", rules)
        self.assertIn(f"Edit(/{self.wt}/.satchel/**)", rules)
        put(os.path.join(self.home, "settings.local.json"), json.dumps({"permissions": {"deny": [f"Read(/{self.wt}/k)"]}}))
        self.assertIn(f"Read(/{self.wt}/k)", pt.load_deny_rules(self.record["settings"]))
        self.assertEqual(self.bash("cat k")[0], 2)
        bad = os.path.join(self.tmp, "bad.json")
        put(bad, "{not json")
        self.assertEqual(pt.load_deny_rules(bad, os.path.join(self.tmp, "none")),
                         pt.load_deny_rules(None, os.path.join(self.tmp, "none")))

    def test_judge_exception_blocks(self):
        from quest.libs import bash
        with mock.patch.object(bash, "deny_write_hits", side_effect=RuntimeError("boom")):
            code, err = self.bash("echo hi")
        self.assertEqual(code, 2)
        self.assertIn("막음", err)
        self.assertIn("RuntimeError", err)

    def test_commit_title_checked(self):
        """작업 세션의 `git commit` 제목은 흐름 규칙 꼴 — 틀리면 막고 맞는 꼴을 알린다."""
        for cmd in ("git commit -m '고침'", "git commit -m 'Q-001 plan: 남의 작업'", "git commit -m 'Q-077 req: x'",
                    "git commit -m 'Q-077 run: 번호 없음'", "git add -A && git commit -qm 'Q-077 planning: x'"):
            with self.subTest(cmd=cmd):
                code, err = self.bash(cmd)
                self.assertEqual(code, 2, cmd)
                self.assertIn("커밋 제목", err)
        self.assertIn("Q-077 <단계>", self.bash("git commit -m '고침'")[1])
        self.start("plan", "run", "done")
        self.commit("Q-077 plan: x", "Q-077 plan-review: x", "Q-077 run: #1 x", "Q-077 review: x")
        for cmd in ("git commit -m 'Q-077 plan: 결정'", "git commit --allow-empty -m 'Q-077 run: #1 구현'",
                    "git commit -m \"$(cat <<'EOF'\nQ-077 done: 끝\n\n본문\nEOF\n)\""):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), (0, ""), cmd)

    def test_commit_without_readable_title_blocked(self):
        """편집기를 여는 꼴·파일에서 읽는 꼴은 막고 `-m`으로 쓰라고 알린다."""
        for cmd in ("git commit", "git commit -a", "git commit -F m.txt", "git commit -C HEAD", "git commit -e -m 'Q-077 plan: x'"):
            with self.subTest(cmd=cmd):
                code, err = self.bash(cmd)
                self.assertEqual(code, 2, cmd)
                self.assertIn("-m", err)

    def test_unsplittable_command_blocks(self):
        code, err = self.bash("echo 'x")
        self.assertEqual(code, 2)
        self.assertIn("나눌 수 없다", err)


class StepGateTest(WorkSession):
    """커밋 때 단계 확인 — 앞 필수 단계 커밋이 있고, 그 단계를 `quest step <단계>`로 들어왔어야 커밋할 수 있다."""

    def test_commit_without_step_blocked(self):
        code, err = self.bash("git commit --allow-empty -m 'Q-077 plan: 결정'")
        self.assertEqual(code, 2)
        self.assertIn("step plan", err)
        self.start("plan")
        self.assertEqual(self.bash("git commit --allow-empty -m 'Q-077 plan: 결정'"), (0, ""))

    def test_commit_without_previous_step_blocked(self):
        self.start("run")
        code, err = self.bash("git commit --allow-empty -m 'Q-077 run: #1 구현'")
        self.assertEqual(code, 2)
        self.assertIn("앞 단계 plan-review 커밋이 없다", err)
        self.commit("Q-077 plan: x", "Q-077 plan-review: x")
        self.assertEqual(self.bash("git commit --allow-empty -m 'Q-077 run: #1 구현'"), (0, ""))

    def test_broken_steps_record_blocks(self):
        """세션 단계 기록이 깨졌으면 막는다 — "기록이 없으니 지나감"이 건너뛰는 길이 되지 않게."""
        from quest.commands import step as step_cmd
        put(os.path.join(self.record["session_dir"], step_cmd.STEPS_FILE), "{깨짐")
        self.assertEqual(self.bash("git commit --allow-empty -m 'Q-077 plan: 결정'")[0], 2)


class LeadSessionTest(WorkSession):
    """리드 세션(작업 세션이 아닌 세션, quest 설정이 있는 저장소) — `git commit`만 좁게 본다."""

    def lead_bash(self, command):
        return self.bash(command, cwd=self.lead)

    def test_quest_titles_checked(self):
        for cmd, want in (("git commit -m 'Q-001 foo: x'", "Q-001 <단계>"), ("git commit -m 'Q-077 plan: x'", "작업 세션"),
                          ("git commit -m 'Q-077 merge: README 끝'", "부명령 merge")):
            with self.subTest(cmd=cmd):
                code, err = self.lead_bash(cmd)
                self.assertEqual(code, 2, cmd)
                self.assertIn(want, err)
        self.assertEqual(self.lead_bash("git commit -m 'Q-078 req: 요구사항'"), (0, ""))

    def test_other_commits_and_work_session_blocks_pass(self):
        """ID로 시작하지 않는 제목·편집기 꼴·작업 세션용 막기(git 되돌리기·질문 창)는 리드 세션에 걸지 않는다."""
        for cmd in ("git commit -m '문서 고침'", "git commit", "git commit -m 'Q-077: 콜론 붙은 말'", "git reset --hard",
                    "git checkout -b x", "git rebase dev/main"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.lead_bash(cmd), (0, ""), cmd)
        self.assertEqual(self.run_hook("AskUserQuestion", cwd=self.lead, questions=[])[0], 0)

    def test_new_requirements_need_id(self):
        put(os.path.join(self.lead, WF, "quests", "Q-078-next", "requirements.md"), REQ.replace("Q-077", "Q-078"))
        git(self.lead, "add", "-A")
        for cmd in ("git commit -m '요구사항'", "git commit -m 'Q-077 req: 다른 번호'", "git commit"):
            with self.subTest(cmd=cmd):
                code, err = self.lead_bash(cmd)
                self.assertEqual(code, 2, cmd)
                self.assertIn("Q-078 req:", err)
        self.assertEqual(self.lead_bash("git commit -m 'Q-078 req: 요구사항'"), (0, ""))

    def test_no_config_or_broken_config(self):
        other = os.path.join(self.tmp, "plain")
        os.makedirs(other)
        git(other, "init", "-q")
        self.assertEqual(self.bash("git commit -m 'Q-001 foo: x'", cwd=other), (0, ""))
        put(os.path.join(self.lead, ".satchel", "quest.json"), "{깨짐")
        code, err = self.lead_bash("git commit -m 'Q-001 foo: x'")
        self.assertEqual(code, 0)
        self.assertIn("판정 불가로 통과", err)

    def test_config_only_in_old_place_says_move(self):
        """설정 파일이 옛 자리에만 있으면 리드 커밋 판정은 지나가되 새 자리로 옮기라는 한 줄을 남긴다."""
        os.makedirs(os.path.join(self.lead, os.path.dirname(settings.OLD_CONFIG_REL)))
        os.rename(os.path.join(self.lead, ".satchel", "quest.json"), os.path.join(self.lead, settings.OLD_CONFIG_REL))
        code, err = self.lead_bash("git commit -m 'Q-001 foo: x'")
        self.assertEqual(code, 0)
        self.assertIn("`.satchel/quest.json`으로 옮겨라", err)


if __name__ == "__main__":
    unittest.main()
