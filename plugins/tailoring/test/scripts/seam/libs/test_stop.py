"""seam/libs/stop.py 시험 — 리뷰어 기다림 판정, 상시 프롬프트·지시 장부."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from test import helpers as testing
from seam.libs import stop as stop_wait
from seam.commands import hold as hold_cmd


PLAN = ("# 계획\n\n## 잰 코드 사실\n\n- x → y\n\n## 결정\n\n- 없음\n\n## 할 일\n\n"
        "- [{a}] 1. 하나 — 시험 `test_a`\n- [{b}] 2. 둘 — 시험 `test_b`\n- [{c}] 3. 문서 — TDD 예외 — 문서만\n\n"
        "## 코드 전 검토\n\n- x\n\n## 구현하며 바뀐 것\n\n- 없음\n")


RETRO_DRAFT = "# 회고\n\n## 끝 검증\n\n- python3 -m unittest → OK\n\n## 어긋난 것\n\n- 없음\n\n## 넘길 일\n\n- 없음\n"


class WaitingTest(unittest.TestCase):
    """리뷰어가 돌고 기다리는 동안 할 일이 남았는데 턴을 끝내면 되돌린다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.realpath(self.tmp.name)
        self.repo_init("piece/P-077-sample")
        p = mock.patch.object(stop_wait, "STATE_FILE", os.path.join(self.repo, ".git", "count.json"))
        p.start()
        self.addCleanup(p.stop)

    def repo_init(self, branch):
        self.work = branch.split("/")[1].split("-")[0] + "-" + branch.split("-")[1]  # piece/P-077-sample → P-077
        self.seam = os.path.join(self.repo, "svc", ".agents", "workflow", "pieces", f"{self.work}-sample")
        os.makedirs(self.seam)
        subprocess.run(["git", "init", "-q", "-b", branch, self.repo], check=True)
        testing.write(self.repo)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"), ("gc.auto", "0"), ("maintenance.auto", "false")):
            subprocess.run(["git", "-C", self.repo, "config", k, v], check=True)
        self.put("requirements.md", f"# r\n\n- 작업: {self.work} · 흐름: seam\n")
        self.commit("req: 요구사항")

    def put(self, name, text):
        path = os.path.join(self.seam, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, tail, rel=None):
        if rel:
            path = os.path.join(self.repo, "svc", rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write("x\n")
        subprocess.run(["git", "-C", self.repo, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "--allow-empty", "-m", f"{self.work} {tail}"], check=True)

    def run_hook(self, message="끝", active=False):
        payload = {"cwd": self.repo, "last_assistant_message": message, "stop_hook_active": active}
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stderr(err):
            code = hold_cmd.main()
        return code, err.getvalue()

    def in_plan_review(self, a=" ", b=" ", c=" "):
        self.put("plan.md", PLAN.format(a=a, b=b, c=c))
        self.commit("plan: 계획")

    def in_code_review(self):
        self.in_plan_review()
        self.commit("plan-review: 반영")
        self.commit("test: #1 #2 시험", "libs/x/src/test/java/ATest.java")
        self.commit("run: #1 #2 구현", "libs/x/src/main/java/A.java")
        self.put("plan.md", PLAN.format(a="x", b="x", c="x"))
        self.commit("run: #3 문서")

    def test_plan_review_running_with_tests_left_blocks(self):
        """남았다고 보는 근거(plan.md 할 일 가운데 시험 커밋이 없는 번호)와 고를 길 둘(시험 커밋·TDD 예외)을 보인다.
        이미 시험 커밋이 있으면(`step test`로 들어온 세션) `step test`를 다시 부르라고 하지 않는다."""
        self.in_plan_review()
        self.commit("test: #1 시험", "libs/x/src/test/java/ATest.java")
        code, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("코드 전 검토", err)
        self.assertIn("plan.md `## 할 일` 가운데 시험 커밋이 없는 번호: #2", err)
        self.assertIn("`P-077 test: #N …`", err)
        self.assertIn("`TDD 예외 — <까닭>`", err)
        self.assertIn("코드 전 검토에서 확정", err)
        self.assertNotIn("step test", err)
        self.assertNotIn("#1", err)
        self.assertNotIn("#3", err)
        self.assertLess(len(err), 400)  # 문구가 길어지지 않게

    def test_plan_review_running_before_any_test_says_step_test(self):
        """시험 커밋이 아직 하나도 없으면 `step test`로 들어가라고 한다."""
        self.in_plan_review()
        code, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("시험 커밋이 없는 번호: #1, #2", err)
        self.assertIn("step test", err)

    def test_plan_review_exempt_written_passes(self):
        """시험이 필요 없는 할 일을 plan.md에 TDD 예외로 적으면(커밋 전이라도) 남은 일이 아니다."""
        self.in_plan_review()
        self.commit("test: #1 시험", "libs/x/src/test/java/ATest.java")
        self.put("plan.md", PLAN.format(a=" ", b=" ", c=" ").replace("2. 둘 — 시험 `test_b`", "2. 둘 — TDD 예외 — 설정 값만"))
        self.assertEqual(self.run_hook()[0], 0)

    def test_plan_review_running_all_tests_written_passes(self):
        self.in_plan_review()
        self.commit("test: #1 #2 시험", "libs/x/src/test/java/ATest.java")
        self.assertEqual(self.run_hook()[0], 0)

    def test_plan_review_report_written_passes(self):
        self.in_plan_review()
        self.put("agents/plan-reviewer.md", "판정: 통과\n")
        self.assertEqual(self.run_hook()[0], 0)

    def test_decision_mode_report_is_not_the_review(self):
        self.in_plan_review()
        self.put("agents/plan-reviewer-P2.md", "판정: 통과\n")
        self.assertEqual(self.run_hook()[0], 2)

    def test_plan_review_done_passes(self):
        self.in_plan_review()
        self.commit("plan-review: 반영")
        self.assertEqual(self.run_hook()[0], 0)

    def test_before_plan_commit_passes(self):
        self.put("plan.md", PLAN.format(a=" ", b=" ", c=" "))
        self.assertEqual(self.run_hook()[0], 0)

    def test_lead_decision_wait_still_blocks(self):
        self.in_plan_review()
        code, err = self.run_hook("결정 요청 보냄\n대기: 리드 — 결정 요청")
        self.assertEqual(code, 2)
        self.assertIn("기다리는 동안", err)

    def test_give_up_after_three(self):
        self.in_plan_review()
        for i in range(3):
            self.assertEqual(self.run_hook("대기: 리드 — 결정 요청", active=i > 0)[0], 2)
        self.assertEqual(self.run_hook("대기: 리드 — 반복 막힘", active=True)[0], 0)

    def test_code_review_running_without_verify_blocks(self):
        self.in_code_review()
        code, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("코드 뒤 검토", err)
        self.assertIn("끝 검증", err)

    def test_code_review_running_with_verify_draft_passes(self):
        self.in_code_review()
        self.put("retro.md", RETRO_DRAFT)
        self.assertEqual(self.run_hook()[0], 0)

    def test_code_review_reports_written_pass(self):
        self.in_code_review()
        self.put("agents/behavior-reviewer.md", "통과\n")
        self.put("agents/docs-reviewer.md", "통과\n")
        self.assertEqual(self.run_hook()[0], 0)

    def test_code_review_one_report_still_running_blocks(self):
        self.in_code_review()
        self.put("agents/behavior-reviewer.md", "통과\n")
        self.assertEqual(self.run_hook()[0], 2)

    def test_code_review_done_passes(self):
        self.in_code_review()
        self.commit("review: 요약")
        self.assertEqual(self.run_hook()[0], 0)

    def test_implementing_is_not_waiting(self):
        """③ 중(할 일이 남음)은 리뷰어 기다림이 아니다."""
        self.in_plan_review()
        self.commit("plan-review: 반영")
        self.commit("test: #1 #2 시험", "libs/x/src/test/java/ATest.java")
        self.assertEqual(self.run_hook()[0], 0)

    def test_plan_review_running_without_todos_blocks(self):
        """`## 결정`까지 쓰고 plan 커밋·리뷰어를 띄운 뒤(R2(가)) 할 일을 안 쓰고 쉬면 되돌린다."""
        self.put("plan.md", PLAN.split("## 할 일")[0] + "## 할 일\n\n<!-- 쓰는 중 -->\n")
        self.commit("plan: 결정")
        code, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("`## 할 일`", err)


class StandingOrdersTest(unittest.TestCase):
    """작업 세션(세션 기록 있음)의 일반 멈춤 막기 — 상시 프롬프트(턴 끝 `남은 지시:`·`대기:` 두 줄)와 지시 장부(열린 항목).
    `seam feed`로 진짜 연 세션에서 본다."""

    END = "남은 지시: 없음\n대기: 리드 — 끝 알림"

    def setUp(self):
        from test.scripts.seam.commands.test_guard import WorkSession
        self.ws = WorkSession("run")
        self.ws.setUp()
        self.addCleanup(self.ws.doCleanups)
        self.wt, self.record = self.ws.wt, self.ws.record
        p = mock.patch.object(stop_wait, "RETRY_SECONDS", 0)
        p.start()
        self.addCleanup(p.stop)

    def run_hook(self, message, cwd=None, transcript=None):
        payload = {"cwd": cwd or self.wt, "last_assistant_message": message, "stop_hook_active": False}
        if transcript:
            payload["transcript_path"] = transcript
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stderr(err):
            code = hold_cmd.main()
        return code, err.getvalue()

    def orders(self, text):
        with open(self.record["orders"], "w", encoding="utf-8") as f:
            f.write(text)

    def test_files_are_where_the_record_says(self):
        self.assertTrue(os.path.isfile(self.record["standing"]))
        self.assertTrue(os.path.isfile(self.record["orders"]))
        status = subprocess.run(["git", "-C", self.wt, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(status, "")  # 지시 장부 자리는 git이 잡지 않는다

    def test_missing_end_lines_are_returned_with_standing_prompt(self):
        self.orders("# 지시\n")
        for msg in ("다 했다", "대기: 리드", "남은 지시: 없음"):
            code, err = self.run_hook(msg)
            self.assertEqual(code, 2, msg)
            self.assertIn("[랄프 루프] 턴이 '남은 지시: …'와 '대기: <기다리는 상대>' 줄 없이 끝났다", err)
            self.assertIn("남은 지시: <없음 | 남은 것과 지금 못 하는 이유>", err)  # 상시 프롬프트를 다시 넣는다
        self.assertEqual(self.run_hook("**남은 지시**: 없음\n**대기**: 리드")[0], 0)

    def test_end_lines_read_from_transcript(self):
        self.orders("# 지시\n")
        t = os.path.join(self.ws.tmp, "t.jsonl")
        with open(t, "w", encoding="utf-8") as f:
            # 기록은 빈칸 없는 JSON 줄(`"role":"assistant"`로 줄을 고른다)
            f.write(json.dumps({"message": {"role": "assistant", "content": [{"type": "text", "text": self.END}]}},
                               separators=(",", ":"), ensure_ascii=False) + "\n")
        self.assertEqual(self.run_hook("", transcript=t)[0], 0)

    def test_open_order_without_wait_tag_blocks(self):
        """처음 연 장부는 열린 항목 하나(대기 표지 없음) — 그대로 끝내면 되돌린다."""
        code, err = self.run_hook(self.END)
        self.assertEqual(code, 2)
        self.assertIn("대기 사유 없는 열린 지시가 1개 있다", err)
        self.assertIn("[지시 목록] 턴을 끝낼 수 없다", err)

    def test_open_order_with_none_left_blocks(self):
        self.orders("- [ ] 2026-11-17 | 리드 | P-077 ①~⑥ | 대기: 리드 — 결정 요청\n")
        code, err = self.run_hook(self.END)
        self.assertEqual(code, 2)
        self.assertIn("열린 지시 1개가 있는데 마지막 답에 '남은 지시: 없음'이 있다", err)
        self.assertEqual(self.run_hook("남은 지시: ①~⑥ — 결정 요청 답 기다림\n대기: 리드 — 결정 요청")[0], 0)

    def test_delivery_failure_wait_is_a_wait_reason(self):
        """리드 전달 실패를 장부에 `| 대기: 리드 — 전달 실패`로 남긴 열린 항목은 대기 사유로 친다 — 그 줄을 '남은 지시:'에 적고
        `대기: 리드 — 전달 실패`로 끝내면 지나간다(일을 다 하고 끝낸 턴). '남은 지시: 없음'이면 되돌린다(다른 열린 항목과 같게)."""
        self.orders("- [x] 2026-11-17 10:00 | 리드 | P-077 ①~⑥ | 확인: inspect 통과\n"
                    "- [ ] 2026-11-17 11:00 | 작업 세션 | 리드에게 끝 알림 | 대기: 리드 — 전달 실패\n")
        msg = "남은 지시: 리드에게 끝 알림 — 전달 실패(두 번), 장부에 남김\n대기: 리드 — 전달 실패"
        self.assertEqual(self.run_hook(msg), (0, ""))
        code, err = self.run_hook("남은 지시: 없음\n대기: 리드 — 전달 실패")
        self.assertEqual(code, 2)
        self.assertIn("열린 지시 1개가 있는데 마지막 답에 '남은 지시: 없음'이 있다", err)

    def test_unreadable_last_answer_blocks_open_orders(self):
        self.orders("- [ ] x | 대기: 리드 — y\n")
        code, err = self.run_hook("")
        self.assertEqual(code, 2)
        self.assertIn("마지막 답을 읽지 못해", err)

    def test_closed_orders_pass(self):
        self.orders("- [x] 2026-11-17 | 리드 | P-077 ①~⑥ | 확인: abc123\n")
        self.assertEqual(self.run_hook(self.END)[0], 0)

    def test_user_wait_still_counts_first(self):
        """`대기: 사용자` 되돌림(횟수 셈)이 먼저다 — 상시 지시·지시 장부 글은 그 판정이 지나간 뒤에만."""
        code, err = self.run_hook("남은 지시: x\n대기: 사용자")
        self.assertEqual(code, 2)
        self.assertIn("사용자를 기다리지 않는다", err)
        self.assertNotIn("[지시 목록]", err)

    def test_lead_checkout_and_no_record_pass(self):
        self.assertEqual(self.run_hook("다 했다", cwd=self.ws.lead), (0, ""))
        os.remove(self.record["standing"])
        os.remove(self.record["orders"])
        self.assertEqual(self.run_hook("다 했다")[0], 0)


if __name__ == "__main__":
    unittest.main()
