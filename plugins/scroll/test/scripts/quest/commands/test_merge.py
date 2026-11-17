"""quest/commands/merge.py 시험 — ① 확인 → ② deliver → ③ 치우기, 멈춘 단계, deliver.verify, custom 닫기, 바뀐 규칙 문장 출력."""
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
from quest.commands import merge as m
from deliver import steps as deliver_steps
from quest.libs import record
from quest.libs.checks import rules as rule_checks


WF = "svc/.agents/workflow"


README = "# 작업\n\n## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n| {work} | t | 진행 | 0771~0780 |\n"


LEDGER = ("# 장부\n\n| ID | 출처 | 받는 쪽 | 내용 | 상태 | 근거 |\n| --- | --- | --- | --- | --- | --- |\n"
          "| C-010 | Q-001 | lead | 옛 일 | 열림 | - |\n\n## 뒤\n")


RETRO = "# 회고\n\n## 끝 검증\n\n- python3 → OK\n\n## 닫을 장부 줄\n\n- 없음\n\n## 넘길 일\n\n{items}"


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def config_with(**sections):
    data = copy.deepcopy(testing.SVC)
    for key, value in sections.items():
        data[key] = value
    return data


class Repo(unittest.TestCase):
    """리드 체크아웃 `<tmp>/lead`(dev/main)와 작업 워크트리 `<tmp>/lead-q-077`, 세션 기록(기본 자리 — git 공통 자리)."""
    WORK = "Q-077"
    CONFIG = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = os.path.realpath(self.tmp.name)
        w = self.WORK
        self.branch = f"quest/{w}-sample"
        self.top, self.wt = os.path.join(root, "lead"), os.path.join(root, "lead-q-077")
        put(os.path.join(self.top, "README.md"), "x\n")
        put(os.path.join(self.top, WF, "quests", "README.md"), README.format(work=w))
        put(os.path.join(self.top, WF, "quests", "carryover.md"), LEDGER)
        put(os.path.join(self.top, WF, "quests", f"{w}-sample", "requirements.md"), f"# r\n\n- 작업: {w} · 결정 번호: 0771~0780 · 흐름: quest\n")
        testing.write(self.top, self.CONFIG)
        self.git(self.top, "init", "-q", "-b", "dev/main")
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"), ("gc.auto", "0"), ("maintenance.auto", "false")):
            self.git(self.top, "config", k, v)
        self.git(self.top, "add", "-A")
        self.git(self.top, "commit", "-q", "-m", "base")
        self.git(self.top, "worktree", "add", "-q", "-b", self.branch, self.wt, "dev/main")
        self.retro = os.path.join(self.wt, WF, "quests", f"{w}-sample", "retro.md")
        put(self.retro, RETRO.format(items="- gateway: 대조 대상 `a|b` 옮기기\n- lead: 끝 검사에서 전체 검사\n"))
        self.git(self.wt, "add", "-A")
        self.git(self.wt, "commit", "-q", "-m", f"{w} done: x")
        self.records = os.path.join(self.top, ".git", "satchel", "quest-sessions")
        self.session_dir = os.path.join(self.records, w)
        self.record = {"work": w, "branch": self.branch, "worktree": self.wt, "lead_top": self.top, "title": f"quest {w}",
                       "session_dir": self.session_dir, "settings": os.path.join(self.session_dir, "settings.json"),
                       "handle": "pane-7", "session_name": "quest-q077"}
        put(os.path.join(self.session_dir, "session.json"), json.dumps(self.record))
        # 끝 확인은 가짜 입구로(이 시험은 합치기 차례만 본다 — 끝 확인 자체는 test_check 몫)
        self.fake_check = os.path.join(root, "fake_quest")
        self.quest_check(0)
        p = mock.patch.object(m, "QUEST", self.fake_check)
        p.start()
        self.addCleanup(p.stop)
        old_cwd = os.getcwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(self.top)
        # 작업 세션이 멈췄는지(pgrep)와 기다림(sleep)은 이 맥의 진짜 프로세스를 보지 않는다
        self.alive_answers = []  # 비면 "멈춤"
        self.sleeps = []
        self.real_session_running = m.session_running
        a = mock.patch.object(m, "session_running", lambda marker: self.alive_answers.pop(0) if self.alive_answers else False)
        a.start()
        self.addCleanup(a.stop)
        self.live_pids = []  # 합치기 전 작업 세션 프로세스(`--name` 표지) — 비면 없음
        self.real_session_pids = m.session_pids
        b = mock.patch.object(m, "session_pids", lambda title: list(self.live_pids))
        b.start()
        self.addCleanup(b.stop)
        s = mock.patch.object(m.time, "sleep", self.sleeps.append)
        s.start()
        self.addCleanup(s.stop)

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout.strip()

    def quest_check(self, code):
        put(self.fake_check, f"import sys\nprint('quest_check: {'통과' if code == 0 else '막힘'}')\nsys.exit({code})\n")

    def set_config(self, data):
        testing.write(self.top, data)
        self.git(self.top, "commit", "-qam", "설정")

    def main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                code = m.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def head_subject(self):
        return self.git(self.top, "log", "-1", "--format=%s", "dev/main")


class MergeTest(Repo):
    def test_warns_when_session_name_is_empty(self):
        self.assertEqual(len(record.record_warnings({"work": "Q-077", "session_name": " "})), 1)
        self.assertEqual(record.record_warnings({"work": "Q-077", "session_name": "x"}), [])

    def test_dry_run_lists_steps_without_merging(self):
        code, out = self.main("Q-077", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn(f"python3 {self.fake_check} end Q-077", out)
        self.assertIn("rebase dev/main", out)
        self.assertIn("merge --ff-only quest/Q-077-sample", out)
        self.assertIn("설정 deliver.verify가 비어 건너뜀", out)
        self.assertIn("세션 닫기: 터미널 none은 닫기가 없어 건너뜀", out)
        self.assertIn("worktree remove", out)
        self.assertNotIn("worktree remove", self.main("Q-077", "--dry-run", "--keep")[1])
        self.assertEqual(self.head_subject(), "base")

    def test_bad_id_and_missing_record(self):
        self.assertNotEqual(self.main("W-077")[0], 0)
        self.assertIn("세션 기록이 없다", str(self.main("Q-078")[0]))

    def test_dirty_worktree_stops(self):
        put(os.path.join(self.wt, "new.txt"), "x")
        code = str(self.main("Q-077", "--keep")[0])
        self.assertIn("커밋 안 한 변경", code)
        self.assertIn("?? new.txt", code)  # 무엇이 남았는지 찍는다

    def test_lead_not_on_integration_stops(self):
        self.git(self.top, "checkout", "-q", "-b", "dev/other")
        self.assertIn("dev/main가 아니다", str(self.main("Q-077", "--keep")[0]))

    def test_rebase_then_ff_with_keep(self):
        put(os.path.join(self.top, "lead.txt"), "x")
        self.git(self.top, "add", "-A")
        self.git(self.top, "commit", "-q", "-m", "lead moved on")
        code, out = self.main("Q-077", "--keep")
        self.assertEqual(code, 0, out)
        self.assertIn("병합: quest/Q-077-sample → dev/main", out)
        self.assertEqual(self.git(self.top, "log", "-3", "--format=%s", "dev/main").splitlines()[1:], ["Q-077 done: x", "lead moved on"])
        self.assertTrue(os.path.isdir(self.wt))

    def test_full_merge_cleans_worktree_branch_and_record(self):
        code, out = self.main("Q-077")
        self.assertEqual(code, 0, out)
        for head in ("[① 확인]", "[② deliver]", "deliver 리베이스:", "병합: ", "[③ 치우기]"):  # 세 단계가 차례로 보인다
            self.assertIn(head, out)
        self.assertLess(out.index("[① 확인]"), out.index("병합: "))
        self.assertLess(out.index("병합: "), out.index("[③ 치우기]"))
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.git(self.top, "branch", "--list", self.branch), "")
        done = os.path.join(self.records, "done", "Q-077")
        self.assertTrue(os.path.exists(os.path.join(done, "session.json")))
        self.assertFalse(os.path.exists(self.session_dir))

    def test_waits_for_work_session_then_stops_if_still_running(self):
        """병합 뒤 정리 전에 작업 세션이 멈추기를 기다린다(20번, 1초씩) — 계속 돌면 정리하지 않고 멈춘다."""
        self.alive_answers = [True] * 20
        code = self.main("Q-077")[0]
        self.assertIn("작업 세션 claude가 아직 돈다", str(code))
        self.assertEqual(len(self.sleeps), 20)
        self.assertTrue(os.path.isdir(self.wt))

    def test_live_session_stops_before_rebase(self):
        """합치기 전에 작업 세션 프로세스(`claude --name <세션 이름>`)가 살아 있으면 리베이스 전에 멈추고 pid를 알린다."""
        self.live_pids = ["4242", "4243"]
        for args in (("Q-077",), ("Q-077", "--keep")):
            code = str(self.main(*args)[0])
            self.assertIn("작업 세션이 아직 돈다(claude --name quest Q-077, pid 4242 4243) — 세션을 끝낸 뒤 다시 부른다.", code)
            self.assertTrue(code.startswith("quest merge — ① 확인에서 멈춤: "), code)
        self.assertEqual(self.head_subject(), "base")
        self.assertEqual(self.git(self.wt, "log", "-1", "--format=%s"), "Q-077 done: x")  # 리베이스·기록 커밋 없음
        self.assertIn("작업 세션 프로세스 없음: pgrep -f -- '--name quest Q-077( |$)'", self.main("Q-077", "--dry-run")[1])


class VerifyTest(Repo):
    """설정 `deliver.verify` — 워크트리에서 돌고 종료 0이어야 합친다. 비면 건너뛴다."""

    def test_verify_passes_and_goes_into_record_body(self):
        self.set_config(config_with(deliver={"verify": "test -f svc/.agents/workflow/quests/Q-077-sample/retro.md"}))
        code, out = self.main("Q-077", "--keep")
        self.assertEqual(code, 0, out)
        body = self.git(self.top, "log", "-1", "--format=%b", "dev/main")
        self.assertEqual(body, "리드 끝 검증: test -f svc/.agents/workflow/quests/Q-077-sample/retro.md → 통과")

    def test_verify_failure_stops_before_record_and_ff(self):
        self.set_config(config_with(deliver={"verify": "echo 빨강; exit 4"}))
        code, _ = self.main("Q-077", "--keep")
        self.assertIn("합치기 전 검사 실패(종료 4): echo 빨강; exit 4", str(code))
        self.assertIn("quest merge — ② deliver에서 멈춤: 검사 — ", str(code))  # 멈춘 단계와 deliver 안 단계
        self.assertIn("빨강", str(code))
        self.assertEqual(self.head_subject(), "설정")
        self.assertEqual(self.git(self.wt, "log", "-1", "--format=%s"), "Q-077 done: x")

    def test_verify_runs_in_worktree(self):
        self.assertIsNone(deliver_steps.verify_problem(self.wt, "test \"$(pwd -P)\" = " + self.wt))
        self.assertIsNone(deliver_steps.verify_problem(self.wt, ""))

    def test_dry_run_shows_verify(self):
        self.set_config(config_with(deliver={"verify": "make check"}))
        self.assertIn("합치기 전 검사(워크트리에서): make check", self.main("Q-077", "--dry-run")[1])


class CloseTest(Repo):
    """세션 닫기 — custom이면 설정 `session.close`(자리표 handle 등), 비면 아무것도 안 한다. 프리셋 닫기는 test_terminal 몫."""

    def custom(self, close):
        self.set_config(config_with(session={"terminal": "custom", "launch": "true", "close": close}))

    def test_close_runs_with_placeholders(self):
        log = os.path.join(os.path.dirname(self.top), "closed.txt")
        self.custom(f"printf '%s %s\\n' {{handle}} {{id}} > {log}")
        code, out = self.main("Q-077")
        self.assertEqual(code, 0, out)
        with open(log, encoding="utf-8") as f:
            self.assertEqual(f.read(), "pane-7 Q-077\n")

    def test_close_failure_warns_and_cleanup_goes_on(self):
        self.custom("exit 9")
        code, out = self.main("Q-077")
        self.assertEqual(code, 0, out)
        self.assertIn("경고: 세션 닫기 명령이 실패했다(종료 9)", out)
        self.assertFalse(os.path.exists(self.wt))

    def test_keep_does_not_close(self):
        log = os.path.join(os.path.dirname(self.top), "closed.txt")
        self.custom(f"touch {log}")
        self.assertEqual(self.main("Q-077", "--keep")[0], 0)
        self.assertFalse(os.path.exists(log))

    def test_custom_without_close_skips(self):
        self.set_config(config_with(session={"terminal": "custom", "launch": "true"}))
        code, out = self.main("Q-077")
        self.assertEqual(code, 0, out)
        self.assertIn("세션 닫기: 설정 session.close가 없어 건너뜀(연 터미널 custom)", out)


class RuleChangeReportTest(Repo):
    """합친 뒤 출력에 회고 `## 바뀐 규칙 문장` 줄을 그대로 싣는다(리드가 보고에 옮김)."""

    LINES = ("- svc/.agents/rules/dependencies.md:deps-03 · `옛 문장` → `새 문장` · 결정 0771\n"
             "- svc/bootstrap/.agents/rules/tests.md:boot-tests-02 · `없음` → `새 줄` · 결정 0772\n")

    def write_retro(self, rules):
        text = RETRO.format(items="- 없음\n").replace("## 넘길 일", "## 바뀐 규칙 문장\n\n" + rules + "\n## 넘길 일")
        put(self.retro, text)
        self.git(self.wt, "add", "-A")
        self.git(self.wt, "commit", "-q", "-m", "Q-077 done: 규칙 줄")

    def test_lines_printed_after_merge(self):
        self.write_retro(self.LINES)
        code, out = self.main("Q-077")
        self.assertEqual(code, 0, out)
        self.assertIn("바뀐 규칙 문장(보고에 옮긴다):\n" + self.LINES, out)
        self.assertLess(out.index("병합: "), out.index("바뀐 규칙 문장"))

    def test_none_printed(self):
        self.write_retro("- 없음\n")
        self.assertIn("바뀐 규칙 문장: 없음\n", self.main("Q-077")[1])

    def test_missing_section_says_unread(self):
        code, out = self.main("Q-077")
        self.assertEqual(code, 0, out)
        self.assertIn("바뀐 규칙 문장: 회고 `## 바뀐 규칙 문장`을 읽지 못했다(", out)

    def test_same_reading_as_quest_check(self):
        rules = self.LINES + "- svc/.agents/rules/x.md:be-x-01 · <옛> → <새> · 결정 0771\n-  없음\n"
        self.write_retro(rules)
        with open(self.retro, encoding="utf-8") as f:
            text = f.read()
        cfg = testing.make()
        self.assertEqual(record.rule_change_lines(self.wt, "Q-077", cfg), rule_checks.rule_items(text))
        self.assertEqual(record.rule_change_lines(self.wt, "Q-077", cfg), self.LINES.splitlines())


class DefaultConfigTest(Repo):
    """필수 둘만 적은 설정이면 나머지는 기본값(기록 `.agents/quests`)으로 돈다."""
    CONFIG = {"branches": {"integration": "main"}, "session": {"terminal": "none"}}

    def setUp(self):
        super().setUp()
        self.git(self.top, "branch", "-m", "dev/main", "main")

    def test_default_integration_and_paths(self):
        code, out = self.main("Q-077", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("rebase main", out)
        code, out = self.main("Q-077", "--keep")
        self.assertEqual(code, 0, out)
        # 기본 자리(.agents/quests)에는 이 작업 기록이 없으니 기록 커밋은 회고·목록을 못 찾고 건너뛴다 — ff만 된다
        self.assertEqual(self.git(self.top, "log", "-1", "--format=%s", "main"), "Q-077 done: x")

    def test_rules_off_prints_no_rule_lines(self):
        """설정 `quest.rule_docs`가 없으면(이 설정 — 필수 둘만) "바뀐 규칙 문장" 확인이 꺼진다 — 합치기가 그 줄을 찍지 않는다(차례 보기에도 없다)."""
        self.assertNotIn("바뀐 규칙 문장", self.main("Q-077", "--dry-run")[1])
        code, out = self.main("Q-077", "--keep")
        self.assertEqual(code, 0, out)
        self.assertNotIn("바뀐 규칙 문장", out)


if __name__ == "__main__":
    unittest.main()
