"""quest/commands/step.py 시험 — 단계 시작 명령: 사슬 확인, 리드 단계·모르는 단계·작업 세션 밖, 안내 내주기, 세션 기록."""
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test import helpers as testing
from quest.commands import step as step_cmd
from quest.libs import config, rules
from test.scripts.quest.commands.test_guard import WorkSession, git  # 바탕(픽스처) — Q-077 작업 세션


class StepTest(WorkSession):
    def step(self, *argv, cwd=None):
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(cwd or self.wt)
        try:
            with redirect_stdout(out):
                code = step_cmd.main(list(argv))
        finally:
            os.chdir(old)
        return code, out.getvalue()

    def commit(self, title):
        git(self.wt, "commit", "-q", "--allow-empty", "-m", title)

    def started(self):
        with open(os.path.join(self.record["session_dir"], step_cmd.STEPS_FILE), encoding="utf-8") as f:
            return json.load(f)

    def test_plan_after_req_gives_guide_and_records(self):
        code, out = self.step("plan")
        self.assertEqual(code, 0, out)
        self.assertIn("Q-077 plan", out)
        self.assertIn("## 할 일", out)  # 안내 파일 몸
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", out)  # 플러그인 자리를 실제 경로로
        self.assertIn(testing.QUEST, out)
        got = self.started()
        self.assertEqual(got["current"], "plan")
        self.assertEqual(got["started"], ["plan"])

    def test_missing_previous_required_commit_stops(self):
        code, out = self.step("plan-review")
        self.assertEqual(code, 1)
        self.assertIn("앞 단계 plan 커밋이 없다", out)
        self.assertFalse(os.path.exists(os.path.join(self.record["session_dir"], step_cmd.STEPS_FILE)))
        self.commit("Q-077 plan: 결정")
        self.assertEqual(self.step("plan-review")[0], 0)
        self.assertEqual(self.step("run")[0], 1)  # run ← plan-review(커밋 아직 없음)
        self.assertEqual(self.step("test")[0], 0)  # test ← plan(start_after) — 검토를 기다리며 시험을 쓴다
        self.commit("Q-077 plan-review: 반영")
        self.assertEqual(self.step("run")[0], 0)
        self.assertEqual(self.step("plan")[0], 0)  # 앞 단계로 되돌아가기
        got = self.started()
        self.assertEqual(got["current"], "plan")
        self.assertEqual(got["started"], ["plan-review", "test", "run", "plan"])

    def test_optional_steps_between_can_be_skipped(self):
        for t in ("Q-077 plan: x", "Q-077 plan-review: x", "Q-077 run: #1 x", "Q-077 review: x"):
            self.commit(t)
        self.assertEqual(self.step("done")[0], 0)  # done ← review(fix는 건너도 된다)
        self.assertEqual(self.step("fix")[0], 0)

    def test_lead_and_unknown_steps_and_outside(self):
        for name, want in (("req", "리드"), ("merge", "부명령 `merge`"), ("impl", "모르는 단계"), ("", "쓰는 법")):
            with self.subTest(name=name):
                code, out = self.step(*([name] if name else []))
                self.assertEqual(code, 2, out)
                self.assertIn(want, out)
        code, out = self.step("plan", cwd=self.lead)
        self.assertEqual(code, 2)
        self.assertIn("작업 세션", out)

    def test_common_guide_has_delivery_failure(self):
        """모든 단계 안내(common.md)에 리드 전달이 안 될 때의 길 — ToolSearch로 불러오기, 한 번 더, 장부에 대기 남기고 이어 가기."""
        code, out = self.step("plan")
        self.assertEqual(code, 0, out)
        for want in ("`select:SendMessage`", "한 번만 더", "`| 대기: 리드 — 전달 실패`", "일은 이어 간다"):
            self.assertIn(want, out)

    def test_review_guides_name_reviewer_model(self):
        """② 코드 전 검토·④ 코드 뒤 검토 안내는 리뷰어를 `model: <설정 session.model>`로 띄우라고 한다(자리표를 채워 찍는다)."""
        self.commit("Q-077 plan: 결정")
        code, out = self.step("plan-review")
        self.assertEqual(code, 0, out)
        self.assertIn("`model: opus`", out)
        self.assertNotIn("<리뷰어 모델>", out)
        for t in ("Q-077 plan-review: x", "Q-077 run: #1 x"):
            self.commit(t)
        with mock.patch.object(config.Config, "model", new_callable=mock.PropertyMock, return_value="haiku"):
            code, out = self.step("review")
        self.assertEqual(code, 0, out)
        self.assertIn("`model: haiku`", out)
        self.assertNotIn("opus", out)

    def test_every_work_step_has_a_guide(self):
        flow = rules.flow()
        for name in flow.hand_steps["작업 세션"]:
            with self.subTest(name=name):
                self.assertTrue(os.path.isfile(step_cmd.guide_path(name)), name)

    def test_real_process(self):
        out = subprocess.run([sys.executable, testing.QUEST, "step", "plan"], cwd=self.wt, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
