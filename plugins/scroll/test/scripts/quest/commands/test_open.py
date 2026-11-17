"""quest/commands/open.py 시험 — 작업 세션 열기(권한 고정·시작 지시·띄우는 명령·연 뒤 기록)."""
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test import helpers as testing
from quest.commands import open as open_cmd
from quest.libs import deny as deny_lib
from quest.libs import prompts, workspace
from quest.libs.context import Context


WF = "svc/.agents/workflow"


REQ = ("# t\n\n- 작업: Q-077 · 결정 번호: 0771~0780 · 브랜치: quest/Q-077-sample · 흐름: quest\n"
       "- 날짜: 2026-11-12 · 요청: 사용자 · 대상: guard\n- 출발: 시험\n\n"
       "## 문제\n\n- 어긋남\n\n## 요구\n\n- R1. 하나\n\n## 범위\n\n- 안: x\n\n## 수용 기준\n\n- 시험 OK\n")


README = "# 작업\n\n## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n| Q-077 | t | 진행 | 0771~0780 |\n"


DENY = [".agents/**", ".githooks/**", ".claude/settings.json", ".claude/skills/**", ".satchel/**"]


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def svc_config(**session):
    data = copy.deepcopy(testing.SVC)
    data["session"] = {**data["session"], **session}
    return data


class Lead(unittest.TestCase):
    """임시 리드 체크아웃 `<tmp>/lead`(dev/main). 기록은 설정(svc 아래), 세션 기록은 기본 자리(git 공통 자리)."""
    SESSION = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.top = os.path.join(self.root, "lead")
        self.home = os.path.join(self.root, "home")  # 작업 세션 홈 — 진짜 홈 settings를 읽지 않게
        os.makedirs(self.home)
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.home})
        env.start()
        self.addCleanup(env.stop)
        put(os.path.join(self.top, WF, "quests", "Q-077-sample", "requirements.md"), REQ)
        put(os.path.join(self.top, WF, "quests", "README.md"), README)
        testing.use_rules(self, "files", paths=DENY)
        testing.write(self.top, svc_config(**self.SESSION))
        self.git("init", "-q", "-b", "dev/main")
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"), ("gc.auto", "0"), ("maintenance.auto", "false")):
            self.git("config", k, v)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "Q-077 req: 요구사항")
        old_cwd = os.getcwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(self.top)
        self.cfg = Context(self.top).cfg
        self.p = workspace.plan("Q-077", "lead-session", self.top, self.cfg)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", cwd or self.top, *args], capture_output=True, text=True, check=True).stdout

    def main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                code = open_cmd.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class PermissionFixedTest(Lead):
    """작업 세션 권한은 늘 `--dangerously-skip-permissions` — 설정에서 받지 않고, 권한 모드가 없다고 멈추는 확인도 없다."""

    def test_launch_always_skips_permissions(self):
        for model in ("opus", "sonnet"):
            cmd = workspace.launch_command(self.p, testing.make(svc_config(model=model)))
            self.assertIn(f"claude --model {model} --dangerously-skip-permissions --plugin-dir ", cmd)
            self.assertEqual(cmd.count("--dangerously-skip-permissions"), 1)
            self.assertNotIn("--permission-mode", cmd)

    def test_old_claude_args_key_stops(self):
        put(os.path.join(self.top, ".satchel", "quest.json"),
            json.dumps(svc_config(claude_args=["--model", "opus", "--permission-mode", "acceptEdits"])))
        code, _ = self.main("Q-077", "--lead", "lead-session")
        self.assertIn("설정 오류: 모르는 키: session.claude_args — session.model로 바뀌었다", str(code))
        self.assertFalse(os.path.exists(self.p["worktree"]))

    def test_deny_bash_from_git_rules(self):
        """세션 settings의 Bash deny는 플러그인 규칙 `src/rules/git.json`의 막는 git 명령에서 만든다(인자 조건이 있으면 그 인자까지)."""
        testing.use_rules(self, "git", commands=[{"command": "stash", "why": "x"},
                                                 {"command": "reset", "args": ["--hard"], "why": "x"}])
        self.assertEqual([d for d in deny_lib.session_settings(self.p, self.cfg)["permissions"]["deny"] if d.startswith("Bash(")],
                         ["Bash(git stash:*)", "Bash(git reset --hard:*)"])

    def test_record_guard_from_git_rules(self):
        """세션 기록의 guard 목록(block_git·block_git_args)도 같은 git.json에서 만든다."""
        testing.use_rules(self, "git", commands=[{"command": "stash", "why": "x"},
                                                 {"command": "reset", "args": ["--hard"], "why": "x"}])
        p = workspace.plan("Q-077", "lead-session", self.top, self.cfg)
        self.assertEqual((p["block_git"], p["block_git_args"]), (["stash"], ["reset:--hard"]))


class TaskAndLaunchTest(Lead):
    def test_task_text_guides_delivery_failure(self):
        """리드에게 전달: SendMessage가 안 보이면 ToolSearch로 불러오고, 실패하면 한 번만 더 — 그래도 안 되면 지시 장부에
        `대기: 리드 — 전달 실패`로 남기고 일은 이어 가며 회고에도 한 줄."""
        text = prompts.task_text(self.p, self.cfg)
        for want in ("`ToolSearch`(`select:SendMessage`)", "한 번만 더", f"`{self.p['orders']}`", "`| 대기: 리드 — 전달 실패`",
                     "일은 이어 간다", "`retro.md` `## 어긋난 것`"):
            self.assertIn(want, text)

    def test_task_text_names_reviewer_model(self):
        """리뷰어(하위 에이전트) 모델은 작업 세션과 같은 모델(설정 `session.model`) — 시작 지시에 그 이름을 박는다."""
        self.assertIn("`model: opus`", prompts.task_text(self.p, self.cfg))
        other = testing.make(svc_config(model="haiku"))
        text = prompts.task_text(self.p, other)
        self.assertIn("`model: haiku`", text)
        self.assertNotIn("opus", text)

    def test_task_text_uses_config_names(self):
        text = prompts.task_text(self.p, self.cfg)
        for want in ("`[Q-077 → lead] 시작: ①`", "SendMessage`(to: `lead-session`)", "`[lead → Q-077] …`",
                     f"`{WF}/quests/Q-077-sample/requirements.md`", f"python3 {testing.QUEST} end Q-077",
                     f"`[Q-077 → lead] 끝: {WF}/quests/Q-077-sample/retro.md`", "대기: 리드 — 결정 요청",
                     "막힌 명령을 스크립트·인터프리터로 돌아가지 않는다", f"먼저 `python3 {testing.QUEST} step plan`"):
            self.assertIn(want, text)
        self.assertIn(f"`python3 {testing.QUEST} step <단계>`", prompts.standing_text(self.p, self.cfg))

    def test_rule_sentence_guide_only_when_rules_on(self):
        """시작 지시의 "규칙 문장 … `## 바뀐 규칙 문장`에 남긴다"는 설정 `quest.rule_docs`의 patterns가 있을 때만."""
        self.assertIn("`## 바뀐 규칙 문장`", prompts.task_text(self.p, self.cfg))  # 시험 설정은 켬
        off = testing.make(testing.svc(rule_docs=None))
        self.assertNotIn("바뀐 규칙 문장", prompts.task_text(self.p, off))

    def test_launch_command(self):
        cmd = workspace.launch_command(self.p, self.cfg)
        self.assertTrue(cmd.startswith(f"cd {self.p['worktree']} && claude --model opus --dangerously-skip-permissions "
                                       f"--plugin-dir {testing.PLUGIN} --name 'quest Q-077' --settings "), cmd)
        self.assertIn(self.p["settings"], cmd)
        self.assertIn(self.p["prompt_file"], cmd)

    def test_one_plugin_root_everywhere(self):
        """띄우는 명령의 `--plugin-dir`, 시작 지시가 부르라는 입구 `src/scripts/quest/main.py`, 플러그인 자리 deny가 모두
        세션 기록의 플러그인 뿌리 한 곳에서 나온다."""
        self.assertEqual(self.p["plugin_root"], testing.PLUGIN)
        self.assertEqual(workspace.quest_entry(self.p), testing.QUEST)
        other = dict(self.p, plugin_root=os.path.join(self.root, "kit"))
        quest = os.path.join(self.root, "kit", "src", "scripts", "quest", "main.py")
        self.assertIn(f"python3 {quest} end Q-077", prompts.task_text(other, self.cfg))
        self.assertNotIn(testing.PLUGIN, prompts.task_text(other, self.cfg))
        cmd = workspace.launch_command(other, self.cfg)
        self.assertIn(f"--plugin-dir {os.path.join(self.root, 'kit')} ", cmd)
        self.assertNotIn(testing.PLUGIN, cmd)
        deny = deny_lib.session_settings(other, self.cfg)["permissions"]["deny"]
        self.assertIn(f"Edit(/{os.path.join(self.root, 'kit')}/**)", deny)
        self.assertNotIn(f"Edit(/{testing.PLUGIN}/**)", deny)

    def test_plugin_dir_always_once(self):
        """작업 세션은 늘 `--plugin-dir <이 플러그인 뿌리>` 하나로 뜬다(설정에서 claude 인자를 받지 않는다)."""
        cmd = workspace.launch_command(self.p, self.cfg)
        self.assertEqual(cmd.count("--plugin-dir"), 1)
        self.assertIn(f"--plugin-dir {testing.PLUGIN}", cmd)

    def test_open_without_launch_prints_command(self):
        code, out = self.main("Q-077", "--lead", "lead-session")
        self.assertEqual(code, 0, out)
        p = self.p
        self.assertIn("설정 `session.terminal`이 none(띄우지 않음)", out)
        self.assertIn(workspace.launch_command(p, self.cfg), out)
        self.assertEqual(self.git("branch", "--show-current", cwd=p["worktree"]).strip(), "quest/Q-077-sample")
        self.assertEqual(self.git("status", "--porcelain", cwd=p["worktree"]), "")
        for name in ("settings.json", "task.md", "session.json"):
            self.assertTrue(os.path.exists(os.path.join(p["session_dir"], name)), name)
        with open(os.path.join(p["session_dir"], "settings.json"), encoding="utf-8") as f:
            self.assertNotIn("hooks", json.load(f))  # 적은 settings에도 훅이 없다
        with open(os.path.join(p["session_dir"], "session.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertIsNone(record["handle"])
        self.assertEqual(record["terminal"], "none")
        self.assertEqual(record["lead_top"], self.top)
        # 훅이 읽는 값: 세션 settings·홈·켜는 git 깃발·상시 프롬프트·지시 장부
        self.assertEqual(record["settings"], os.path.join(p["session_dir"], "settings.json"))
        self.assertEqual(record["home"], os.path.realpath(self.home))
        self.assertEqual(record["plugin_root"], testing.PLUGIN)
        self.assertIn(f"--plugin-dir {testing.PLUGIN}", out)
        self.assertEqual((record["block_git"], record["block_git_args"]), (["push", "checkout", "restore", "stash", "clean", "switch", "merge", "pull", "rebase", "am"], ["reset:--hard"]))
        self.assertEqual(record["standing"], os.path.join(p["session_dir"], "standing.md"))
        self.assertEqual(record["orders"], os.path.join(p["worktree"], ".quest-session", "orders.md"))
        with open(record["standing"], encoding="utf-8") as f:
            standing = f.read()
        for want in ("남은 지시: <없음 | 남은 것과 지금 못 하는 이유>\n대기: <기다리는 상대>", record["orders"], "| 대기: <상대> — <이유>"):
            self.assertIn(want, standing)
        with open(record["orders"], encoding="utf-8") as f:
            self.assertRegex(f.read(), r"\n- \[ \] \S+ \S+ \| 리드 \| Q-077 ①~⑥\(스킬 quest\)")
        self.assertIn("standing.md", prompts.task_text(p, self.cfg))

    def test_open_with_custom_launch_records_handle(self):
        log = os.path.join(self.root, "launched.txt")
        testing.write(self.top, svc_config(terminal="custom",
                                           launch=f"printf '%s\\n' {{title}} {{prompt_file}} > {log}; echo pane-7"))
        self.git("commit", "-qam", "설정")
        code, out = self.main("Q-077", "--lead", "lead-session")
        self.assertEqual(code, 0, out)
        self.assertNotIn("띄우지 않음", out)
        with open(log, encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), ["quest Q-077", self.p["prompt_file"]])
        with open(os.path.join(self.p["session_dir"], "session.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual((record["terminal"], record["handle"]), ("custom", "pane-7"))

    def test_launch_failure_prints_cleanup(self):
        testing.write(self.top, svc_config(terminal="custom", launch="exit 3"))
        self.git("commit", "-qam", "설정")
        code, _ = self.main("Q-077", "--lead", "lead-session")
        self.assertIn("세션 띄우기 명령이 실패했다(종료 3)", str(code))
        self.assertIn("worktree remove --force", str(code))

    def test_dry_run_has_no_side_effects(self):
        code, out = self.main("Q-077", "--lead", "lead-session", "--dry-run")
        self.assertEqual(code, 0, out)
        got = json.loads(out)
        self.assertEqual(got["problems"], [])
        self.assertIsNone(got["launch"])
        self.assertFalse(os.path.exists(self.p["worktree"]))
        self.assertFalse(os.path.exists(self.p["session_dir"]))

    def test_problems_stop_before_side_effects(self):
        code, _ = self.main("Q-077")
        self.assertIn("--lead <리드 세션 이름>이 없다", str(code))
        self.assertFalse(os.path.exists(self.p["worktree"]))

    def test_req_commit_needed_on_integration(self):
        """여는 작업의 `<ID> req:` 커밋이 통합 브랜치에 있어야 연다 — 요구사항 파일이 커밋돼 있어도 제목이 다르면 멈춘다."""
        self.assertNotIn("req", "\n".join(workspace.check_lead(self.p, self.cfg)))
        self.git("commit", "-q", "--amend", "-m", "요구사항 더함")
        found = "\n".join(workspace.check_lead(self.p, self.cfg))
        self.assertIn("`Q-077 req: …` 커밋이 dev/main에 없다", found)
        code, _ = self.main("Q-077", "--lead", "lead-session")
        self.assertIn("Q-077 req:", str(code))
        self.assertFalse(os.path.exists(self.p["worktree"]))
        self.git("commit", "-q", "--allow-empty", "-m", "Q-076·Q-077 req: 묶음")  # 묶음 제목도 받는다
        self.assertEqual(workspace.check_lead(self.p, self.cfg), [])

    def test_bad_config_stops(self):
        put(os.path.join(self.top, ".satchel", "quest.json"), json.dumps({"nope": 1}))
        code, _ = self.main("Q-077", "--lead", "x")
        self.assertIn("설정 오류: 모르는 키: nope", str(code))


if __name__ == "__main__":
    unittest.main()
