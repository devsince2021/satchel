"""플러그인 훅 시험 — src/hooks/hooks.json이 부르는 경로·부명령, 리드 세션·다른 자리·설정 없음에서 해가 없음, 두 python으로 진짜 프로세스."""
import json
import os
import re
import subprocess
import sys
import tempfile
from unittest import mock

from test import helpers as testing
from seam.libs import workspace
from test.scripts.seam.commands.test_guard import WorkSession  # 바탕(픽스처)
from test.scripts.seam.commands.test_feed import Lead  # 바탕(픽스처)
from test.scripts.seam.test_main import Repo  # 바탕(픽스처)


HOOKS_JSON = os.path.join(testing.PLUGIN, "src", "hooks", "hooks.json")


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout


GLOB_DOTDOT = "cat $P/domain/src/main/java/*/../ -h; find …; grep …"  # 하위 에이전트가 확인 창에 멈추던 꼴


PYTHONS = [sys.executable] + [p for p in ("/usr/bin/python3",) if os.path.exists(p)]


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def hook_env(home):
    return dict(os.environ, CLAUDE_PLUGIN_ROOT=testing.PLUGIN, CLAUDE_CONFIG_DIR=home)


class PluginHookTest(Repo):
    """플러그인 Stop 훅은 설치된 모든 세션의 Stop마다 돈다 — 작업 브랜치에서만 판정하고 그 밖에서는 0, 출력 없음, 파일 없음."""

    def payload(self, cwd, message="다 했다\n대기: 사용자"):
        return {"cwd": cwd, "last_assistant_message": message, "stop_hook_active": False, "hook_event_name": "Stop"}

    def test_lead_session_on_integration_branch_passes(self):
        self.assertEqual(self.hook_command(self.payload(self.repo)), (0, "", ""))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "stop-wait.json")))

    def test_other_places_pass(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.assertEqual(self.hook_command(self.payload(os.path.realpath(outside.name))), (0, "", ""))
        git(self.repo, "checkout", "-q", "-b", "feature/x")
        self.assertEqual(self.hook_command(self.payload(self.repo)), (0, "", ""))
        code, _, _ = self.hook_command({"cwd": self.repo})  # 마지막 답이 없음
        self.assertEqual(code, 0)

    def test_work_branch_user_wait_is_returned(self):
        git(self.repo, "checkout", "-q", "-b", "piece/P-001-sample")
        code, out, err = self.hook_command(self.payload(self.repo))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("[stop_wait] 끝낼 수 없다: `대기: 사용자`", err)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")  # 횟수 파일은 git 자리에
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".git", "stop-wait.json")))

    def test_broken_input_passes(self):
        out = subprocess.run([sys.executable, testing.SEAM, "hold"], input="{", capture_output=True, text=True,
                             cwd=self.repo)
        self.assertEqual(out.returncode, 0)
        self.assertIn("판정 불가로 통과", out.stderr)


class NoConfigTest(Repo):
    """설정 파일이 없으면 사람이 부르는 부명령은 필수 둘(branches.integration·session.terminal)을 적으라며 멈추고(2),
    훅은 작업 브랜치에서만 판정 불가 한 줄을 남기고 지나간다(그 밖에서는 설정을 읽지 않고 말없이 0)."""
    CONFIG = None
    WANT = "설정에 branches.integration·session.terminal을 적어라"

    def test_commands_stop_with_required_keys(self):
        for args, head in ((("status", "P-001"), "seam_check"), (("inspect", "P-001"), "seam_check"), (("carryover",), "check_carryover")):
            code, out, _ = self.seam(*args)
            self.assertEqual(code, 2, args)
            self.assertTrue(out.startswith(f"{head}: 설정 오류: {self.WANT}"), out)
        code, _, err = self.seam("feed", "P-001", "--lead", "x")
        self.assertEqual(code, 1)
        self.assertIn(self.WANT, err)
        self.assertIn('{"branches": {"integration": "<통합 브랜치>"}}', err)

    def test_hooks_pass_silently_off_work_branch(self):
        self.assertEqual(self.hook_command(self.payload(self.repo)), (0, "", ""))
        out = subprocess.run([sys.executable, testing.SEAM, "guard"], capture_output=True, text=True, cwd=self.repo,
                             input=json.dumps({"cwd": self.repo, "tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.assertEqual((out.returncode, out.stderr), (0, ""))

    def test_hooks_leave_one_line_on_work_branch(self):
        git(self.repo, "checkout", "-q", "-b", "piece/P-001-sample")
        code, out, err = self.hook_command(self.payload(self.repo))
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn("판정 불가로 통과", err)
        self.assertIn(self.WANT, err)
        out = subprocess.run([sys.executable, testing.SEAM, "guard"], capture_output=True, text=True, cwd=self.repo,
                             input=json.dumps({"cwd": self.repo, "tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.assertEqual(out.returncode, 0)
        self.assertEqual(len(out.stderr.splitlines()), 1)
        self.assertIn(self.WANT, out.stderr)

    payload = PluginHookTest.payload


class HookProcessTest(WorkSession):
    """hooks.json의 명령 그대로(셸, `${CLAUDE_PLUGIN_ROOT}`)를 진짜 프로세스로 — 두 python 모두."""

    def hook(self, payload, python=None):
        with open(HOOKS_JSON, encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]["PreToolUse"]
        matcher = next(b for b in hooks if re.fullmatch(b["matcher"], payload["tool_name"]))
        command = matcher["hooks"][0]["command"]
        if python:
            command = command.replace("python3 ", python + " ", 1)
        out = subprocess.run(["sh", "-c", command], input=json.dumps(payload), env=hook_env(self.home),
                             capture_output=True, text=True, cwd=payload.get("cwd"))
        return out.returncode, out.stderr

    def test_matchers(self):
        with open(HOOKS_JSON, encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]["PreToolUse"]
        self.assertEqual([b["matcher"] for b in hooks], ["Bash", "Agent|Task|AskUserQuestion"])

    def test_work_session_blocks_and_passes(self):
        cases = (
            ({"tool_name": "AskUserQuestion", "tool_input": {"questions": []}}, 2),          # (가)
            ({"tool_name": "Bash", "tool_input": {"command": f"git -C {self.wt} reset --hard"}}, 2),  # (나)
            ({"tool_name": "Bash", "tool_input": {"command": f"git -C {self.lead} commit -m x"}}, 2),  # (다)
            ({"tool_name": "Bash", "tool_input": {"command": "echo '{}' > .studio/tailoring.json"}}, 2),  # (라)
            ({"tool_name": "Agent", "tool_input": {"prompt": "할 일: x"}}, 2),                  # (마)
            ({"tool_name": "Bash", "tool_input": {"command": GLOB_DOTDOT}}, 2),
            ({"tool_name": "Bash", "tool_input": {"command": "git status"}}, 0),                # (바)
            ({"tool_name": "Bash", "tool_input": {"command": "python3 -m unittest discover -s tests"}}, 0),
            ({"tool_name": "Bash", "tool_input": {"command": "echo x > notes.md"}}, 0),
        )
        for python in PYTHONS:
            for payload, want in cases:
                with self.subTest(python=python, payload=payload):
                    code, err = self.hook({**payload, "cwd": self.wt}, python)
                    self.assertEqual(code, want, err)
                    lead_code, lead_err = self.hook({**payload, "cwd": self.lead}, python)  # (사)
                    self.assertEqual((lead_code, lead_err), (0, ""))

    def test_outside_git_passes(self):
        for python in PYTHONS:
            self.assertEqual(self.hook({"tool_name": "AskUserQuestion", "tool_input": {}, "cwd": self.tmp}, python), (0, ""))

    def test_home_dot_read_under_every_python(self):
        """홈 settings `Read(<홈>/.ssh/**)`는 Read 도구만이 아니라 셸 읽기(`cat`·`head`)도 막는다."""
        fake = os.path.join(self.tmp, "fake-home")
        os.makedirs(os.path.join(fake, ".ssh"))
        put(os.path.join(self.home, "settings.json"), json.dumps({"permissions": {"deny": [f"Read(/{fake}/.ssh/**)"]}}))
        for python in PYTHONS:
            for cmd, want in (("cat ~/.ssh/config", 2), ("head -1 $HOME/.ssh/known_hosts", 2), ("ls ~/.sshx", 0)):
                with self.subTest(python=python, cmd=cmd), mock.patch.dict(os.environ, {"HOME": fake}):
                    code, err = self.hook({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.wt}, python)
                    self.assertEqual(code, want, err)

    def test_wrapper_script_with_bad_glob_passes_under_every_python(self):
        """3.9 fnmatch가 `[^-[`를 정규식 오류로 내던 감싸기 본문(sed 식)은 판정 예외로 막히지 않는다."""
        put(os.path.join(self.wt, "w"), "#!/bin/sh\nquote() { printf %s\\\\n \"$1\" | sed ' s~[^-[:alnum:]+,./:=@_]~\\\\&~g; '; }\n")
        os.chmod(os.path.join(self.wt, "w"), 0o755)
        for python in PYTHONS:
            for cmd in ("./w -q help", f"cd {self.wt} && ./w -q help"):
                with self.subTest(python=python, cmd=cmd):
                    self.assertEqual(self.hook({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.wt}, python)[0], 0)


class HookFileTest(Lead):
    """훅 파일 꼴."""

    def test_plugin_hook_calls_entry_stop_hook(self):
        """훅은 플러그인 src/hooks/hooks.json 하나 — Stop은 입구 `seam hold`, PreToolUse(Bash와 Agent|Task|AskUserQuestion)는 `seam guard`."""
        self.assertTrue(os.path.exists(workspace.HOOKS_JSON))
        with open(workspace.HOOKS_JSON, encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]
        self.assertEqual(sorted(hooks), ["PreToolUse", "Stop"])
        self.assertEqual(len(hooks["Stop"]), 1)
        self.assertEqual([h["command"] for h in hooks["Stop"][0]["hooks"]],
                         ['python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/seam/main.py" hold'])
        self.assertEqual([b["matcher"] for b in hooks["PreToolUse"]], ["Bash", "Agent|Task|AskUserQuestion"])
        for block in hooks["PreToolUse"]:
            self.assertEqual([h["command"] for h in block["hooks"]],
                             ['python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/seam/main.py" guard'])


if __name__ == "__main__":
    unittest.main()
