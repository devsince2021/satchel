"""quest/libs/terminals.py 시험 — 터미널 프리셋(src/presets/terminals.json)으로 작업 세션 띄우기·닫기."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from test import helpers as testing
from quest.libs import record as merge_record
from quest.libs import terminals as terminal
from test.scripts.quest.commands.test_open import Lead, svc_config


FAKE = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_TERM_DIR"]
name = os.path.basename(sys.argv[0])
with open(os.path.join(d, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps([name, *sys.argv[1:]]) + "\n")
kind = "-".join(a for a in sys.argv[1:3] if not a.startswith("-"))
n_path = os.path.join(d, kind + ".n")
n = int(open(n_path).read()) if os.path.exists(n_path) else 0
open(n_path, "w").write(str(n + 1))
for path in (os.path.join(d, f"{kind}.{n}.out"), os.path.join(d, f"{kind}.out")):
    if os.path.exists(path):
        sys.stdout.write(open(path, encoding="utf-8").read())
        break
code_path = os.path.join(d, kind + ".code")
sys.exit(int(open(code_path).read()) if os.path.exists(code_path) else 0)
'''


P_OPEN = {"work": "Q-077", "title": "quest Q-077", "command": "cd /w/lead-q-077 && claude --name 'quest Q-077'",
          "worktree": "/w/lead-q-077", "settings": "/s/settings.json", "prompt_file": "/s/task.md", "lead_name": "lead",
          "branch": "quest/Q-077-sample"}


RECORD = {"work": "Q-077", "title": "quest Q-077", "worktree": "/w/lead-q-077", "branch": "quest/Q-077-sample",
          "settings": "/s/settings.json"}


ORCA_ENV = {"ORCA_WORKTREE_ID": "repo-1::/w/lead"}


class Fake(unittest.TestCase):
    """가짜 orca·tmux를 PATH 앞에 둔다. answer(종류, 글, 차례)로 답을 정하고 calls()로 받은 인자를 본다."""

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        bin_dir = os.path.join(self.dir, "bin")
        os.makedirs(bin_dir)
        for name in ("orca", "tmux"):
            path = os.path.join(bin_dir, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(FAKE)
            os.chmod(path, 0o755)
        env = {"PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""), "FAKE_TERM_DIR": self.dir}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for var in ("ORCA_WORKTREE_ID", "TMUX"):
            if var in os.environ:
                q = mock.patch.dict(os.environ)
                q.start()
                self.addCleanup(q.stop)
                del os.environ[var]
        self.sleeps = []
        s = mock.patch.object(terminal, "sleep", self.sleeps.append)
        s.start()
        self.addCleanup(s.stop)
        self.cfg = testing.make()

    def answer(self, kind, text=None, nth=None, code=None):
        if text is not None:
            with open(os.path.join(self.dir, f"{kind}.{nth}.out" if nth is not None else f"{kind}.out"), "w", encoding="utf-8") as f:
                f.write(text)
        if code is not None:
            with open(os.path.join(self.dir, f"{kind}.code"), "w", encoding="utf-8") as f:
                f.write(str(code))

    def calls(self):
        path = os.path.join(self.dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def env(self, **values):
        p = mock.patch.dict(os.environ, values)
        p.start()
        self.addCleanup(p.stop)


class NoneTest(Fake):
    def test_none_does_not_launch_or_close(self):
        self.assertEqual(terminal.problems("none"), [])
        self.assertIsNone(terminal.launch("none", self.cfg, P_OPEN))
        self.assertIsNone(terminal.launch_line("none", self.cfg, P_OPEN))
        self.assertEqual(terminal.close(dict(RECORD, terminal="none", handle="x"), self.cfg),
                         ["세션 닫기: 터미널 none은 닫기가 없어 건너뜀"])
        self.assertEqual(self.calls(), [])


class OrcaTest(Fake):
    def test_needs_worktree_id_before_open(self):
        got = terminal.problems("orca")
        self.assertEqual(len(got), 1)
        self.assertIn("리드 세션이 Orca 탭 밖이다(환경 변수 ORCA_WORKTREE_ID 없음)", got[0])
        self.env(**ORCA_ENV)
        self.assertEqual(terminal.problems("orca"), [])

    def test_needs_executable(self):
        """PATH에 없으면 Orca 앱 안의 자리, 둘 다 없으면 열기 전에 멈춘다."""
        self.env(**ORCA_ENV)
        data = testing.plugin_rules("terminals")
        data["presets"]["orca"]["bin"]["fallbacks"] = [os.path.join(self.dir, "없음", "orca")]
        testing.use_rules(self, "terminals", presets=data["presets"])
        with mock.patch.object(terminal, "which", lambda name: None):
            got = terminal.problems("orca")
            self.assertTrue(any("실행 파일이 없다(PATH의 orca·" in x for x in got), got)
            with self.assertRaises(terminal.TerminalError):
                terminal.launch("orca", self.cfg, P_OPEN)
        fallback = os.path.join(self.dir, "bin", "orca")
        data["presets"]["orca"]["bin"]["fallbacks"] = [fallback]
        testing.use_rules(self, "terminals", presets=data["presets"])
        with mock.patch.object(terminal, "which", lambda name: None):
            self.assertEqual(terminal.problems("orca"), [])
            self.assertEqual(terminal.find_bin(terminal.preset("orca")["bin"]), fallback)

    def test_launch_command_shape_and_json_handle(self):
        self.env(**ORCA_ENV)
        self.answer("terminal-create", json.dumps({"ok": True, "result": {"terminal": {"handle": "term_ab-12"}}}))
        got = terminal.launch("orca", self.cfg, P_OPEN)
        self.assertEqual(got, {"handle": "term_ab-12", "note": None})
        self.assertEqual(self.calls(), [["orca", "terminal", "create", "--worktree", "id:repo-1::/w/lead", "--title", "quest Q-077",
                                         "--command", P_OPEN["command"], "--json"]])

    def test_handle_from_text_when_json_breaks(self):
        self.env(**ORCA_ENV)
        self.answer("terminal-create", "made terminal term_0f-9 (json off)\n")
        self.assertEqual(terminal.launch("orca", self.cfg, P_OPEN)["handle"], "term_0f-9")
        self.assertEqual(len(self.calls()), 1)

    def test_handle_found_by_title_after_retries(self):
        """핸들을 못 받으면 목록(`terminal list --json`)에서 title로 다시 찾는다 — 사이에 기다림, 다른 제목은 안 집는다."""
        self.env(**ORCA_ENV)
        self.answer("terminal-create", json.dumps({"ok": True, "result": {}}))
        self.answer("terminal-list", json.dumps({"result": {"terminals": [{"title": "quest Q-0770", "handle": "term_x"}]}}), nth=0)
        self.answer("terminal-list", json.dumps({"result": {"terminals": [{"title": "quest Q-077", "handle": "term_found"}]}}), nth=1)
        got = terminal.launch("orca", self.cfg, P_OPEN)
        self.assertEqual(got, {"handle": "term_found", "note": None})
        lists = [c for c in self.calls() if c[1:3] == ["terminal", "list"]]
        self.assertEqual(lists, [["orca", "terminal", "list", "--worktree", "id:repo-1::/w/lead", "--json"]] * 2)
        self.assertEqual(self.sleeps, [2])

    def test_handle_lost_after_all_tries(self):
        self.env(**ORCA_ENV)
        self.answer("terminal-create", "")
        got = terminal.launch("orca", self.cfg, P_OPEN)
        self.assertIsNone(got["handle"])
        self.assertIn("핸들을 받지 못했다 — 탭은 떴을 수 있다", got["note"])
        self.assertEqual(len([c for c in self.calls() if c[1:3] == ["terminal", "list"]]), 3)
        self.assertEqual(self.sleeps, [2, 2])

    def test_launch_failure(self):
        self.env(**ORCA_ENV)
        self.answer("terminal-create", "no runtime\n", code=3)
        with self.assertRaises(terminal.TerminalError) as e:
            terminal.launch("orca", self.cfg, P_OPEN)
        self.assertIn("세션 띄우기 명령이 실패했다(종료 3)", str(e.exception))
        self.assertIn("no runtime", str(e.exception))

    def test_close_waits_then_closes_tab(self):
        cfg = testing.make(svc_config(terminal="orca"))
        warnings = terminal.close(dict(RECORD, terminal="orca", handle="term_ab"), cfg)
        self.assertEqual(warnings, [])
        self.assertEqual(self.calls(), [
            ["orca", "terminal", "wait", "--terminal", "term_ab", "--for", "tui-idle", "--timeout-ms", "15000"],
            ["orca", "terminal", "close", "--terminal", "term_ab", "--tab"]])

    def test_close_goes_on_after_failure(self):
        """쉼 기다림이 실패해도(시간 초과 등) 탭 닫기는 한다 — 실패는 경고로."""
        self.answer("terminal-wait", code=1)
        warnings = terminal.close(dict(RECORD, terminal="orca", handle="term_ab"), self.cfg)
        self.assertEqual([c[2] for c in self.calls()], ["wait", "close"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("경고: 세션 닫기 명령이 실패했다(종료 1)", warnings[0])

    def test_close_without_handle_skips(self):
        got = terminal.close(dict(RECORD, terminal="orca", handle=None), self.cfg)
        self.assertEqual(got, ["세션 닫기: 세션 기록에 handle이 없어 건너뜀(터미널 orca) — 창·탭은 손으로 닫는다"])
        self.assertEqual(self.calls(), [])


class TmuxTest(Fake):
    def test_needs_tmux_session(self):
        self.assertIn("tmux 세션 밖이다(환경 변수 TMUX 없음)", terminal.problems("tmux")[0])
        self.env(TMUX="/tmp/tmux-1/default,1,0")
        self.assertEqual(terminal.problems("tmux"), [])

    def test_launch_new_window_and_close(self):
        self.env(TMUX="/tmp/tmux-1/default,1,0")
        self.answer("new-window", "@7\n")
        got = terminal.launch("tmux", self.cfg, P_OPEN)
        self.assertEqual(got, {"handle": "@7", "note": None})
        self.assertEqual(self.calls(), [["tmux", "new-window", "-d", "-n", "quest Q-077", "-P", "-F", "#{window_id}", P_OPEN["command"]]])
        self.assertEqual(terminal.close(dict(RECORD, terminal="tmux", handle="@7"), self.cfg), [])
        self.assertEqual(self.calls()[-1], ["tmux", "kill-window", "-t", "@7"])

    def test_odd_output_is_not_a_handle(self):
        self.env(TMUX="/tmp/tmux-1/default,1,0")
        self.answer("new-window", "warning: x\n")
        got = terminal.launch("tmux", self.cfg, P_OPEN)
        self.assertIsNone(got["handle"])
        self.assertIn("핸들을 받지 못했다", got["note"])


class CustomTest(Fake):
    def test_custom_uses_config_templates(self):
        log = os.path.join(self.dir, "custom.txt")
        cfg = testing.make(svc_config(terminal="custom", launch=f"printf '%s\\n' {{title}} > {log}; echo pane-3",
                                      close=f"echo closed {{handle}} >> {log}"))
        self.assertEqual(terminal.launch("custom", cfg, P_OPEN), {"handle": "pane-3", "note": None})
        self.assertEqual(terminal.close(dict(RECORD, terminal="custom", handle="pane-3"), cfg), [])
        with open(log, encoding="utf-8") as f:
            self.assertEqual(f.read(), "quest Q-077\nclosed pane-3\n")


class OpenWithOrcaTest(Lead, Fake):
    """`quest open`이 프리셋을 거친다 — ORCA_WORKTREE_ID 없으면 열기 전에 멈추고, 있으면 띄워 세션 기록에 터미널·핸들을 남긴다."""

    def setUp(self):
        Fake.setUp(self)
        Lead.setUp(self)
        testing.write(self.top, svc_config(terminal="orca"))
        self.git("commit", "-qam", "설정")

    def test_without_worktree_id_stops_before_side_effects(self):
        code, _ = self.main("Q-077", "--lead", "lead-session")
        self.assertIn("리드 세션이 Orca 탭 밖이다", str(code))
        self.assertFalse(os.path.exists(self.p["worktree"]))
        self.assertEqual(self.calls(), [])

    def test_open_records_terminal_and_handle(self):
        self.env(**ORCA_ENV)
        self.answer("terminal-create", json.dumps({"result": {"terminal": {"handle": "term_q77"}}}))
        code, out = self.main("Q-077", "--lead", "lead-session")
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.p["session_dir"], "session.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual((record["terminal"], record["handle"]), ("orca", "term_q77"))
        call = self.calls()[0]
        command = call[call.index("--command") + 1]
        self.assertTrue(command.startswith(f"cd {self.p['worktree']} && claude --model opus --dangerously-skip-permissions "), command)

    def test_lost_handle_keeps_session_and_warns(self):
        self.env(**ORCA_ENV)
        code, out = self.main("Q-077", "--lead", "lead-session")
        self.assertEqual(code, 0, out)
        self.assertIn("경고: 터미널 orca: 핸들을 받지 못했다 — 탭은 떴을 수 있다", out)
        self.assertTrue(os.path.exists(self.p["worktree"]))
        with open(os.path.join(self.p["session_dir"], "session.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertIsNone(record["handle"])
        self.assertIn("탭은 떴을 수 있다", record["launch_note"])

    def test_merge_dry_run_shows_close_steps(self):
        record = dict(RECORD, terminal="orca", handle="term_q77")
        orca = os.path.join(self.dir, "bin", "orca")
        self.assertEqual(merge_record.close_lines(record, self.cfg),
                         [f"세션 닫기: {orca} terminal wait --terminal term_q77 --for tui-idle --timeout-ms 15000",
                          f"세션 닫기: {orca} terminal close --terminal term_q77 --tab"])


if __name__ == "__main__":
    unittest.main()
