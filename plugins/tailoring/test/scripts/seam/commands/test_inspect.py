"""seam/commands/inspect.py 시험 — 끝 확인 출력과 종료 코드."""
import io
import os
import unittest
from contextlib import redirect_stdout

from seam.commands import inspect as inspect_cmd
from seam.libs import checks, config
from seam.libs.text import read
from test.scripts.seam.libs.test_checks import Base, tearDownModule  # 바탕(픽스처)


TABLE = "| # | 지적 | 출처 | 등급 | 한 일 | 시험 |\n| --- | --- | --- | --- | --- | --- |\n"


RETRO = ("# 회고\n\n## 끝 검증\n\n- python3 -m unittest → OK\n\n## 어긋난 것\n\n- 없음\n\n"
         "## 바뀐 규칙 문장\n\n- 없음\n\n## 닫을 장부 줄\n\n- 없음\n\n## 넘길 일\n\n- 없음\n")


V2 = "P-061"


V2_PIECE = "pieces/P-061-sample"


V2_REQ = ("# t\n\n- 작업: P-061 · 결정 번호: 0611~0620 · 브랜치: piece/P-061-sample · 흐름: seam\n"
          "- 날짜: 2026-11-12 · 요청: 사용자 · 대상: guard\n- 출발: 시험\n\n"
          "## 문제\n\n- 어긋남\n\n## 요구\n\n- R1. 하나\n\n## 범위\n\n- 안: x\n\n## 수용 기준\n\n- 시험 OK\n")


V2_PLAN = ("# 계획\n\n## 잰 코드 사실\n\n- `rg x` → 3\n\n## 결정\n\n- 없음\n\n## 할 일\n\n"
           "- [x] 1. 하나 — 시험 `test_a`\n- [x] 2. 둘 — 시험 `test_b`\n- [x] 3. 문서 — TDD 예외 — 문서만\n\n"
           "## 코드 전 검토\n\n- Minor 1 — 둠\n\n## 구현하며 바뀐 것\n\n- 없음\n")


V2_RETRO = RETRO.replace("## 넘길 일\n\n- 없음\n", "## 넘길 일\n\n- gateway: 대조 대상 옮기기\n")


V2_REVIEW = ("# 리뷰\n\n## 동작\n\n- I1 경계\n\n## 문서·규칙\n\n- 없음\n\n## 반영\n\n" + TABLE
             + "| 1 | 경계 | 동작 | Important | 고침 abc1234 | test_edge |\n| 2 | 말 | 문서·규칙 | Minor | 고침 — 낱말 맞춤 | — |\n")


class EndTest(Base):
    def test_clean_passes(self):
        self.v2_finish()
        self.assertEqual(self.inspect(), [])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(inspect_cmd.main([V2], self.ctx), 0)
        self.assertIn("seam_check: 통과", out.getvalue())

    def test_no_piece_folder(self):
        self.assertEqual(checks.end_problems(self.ctx, "P-099"), ["svc/.agents/workflow/pieces/P-099-*/ 없음"])

    def test_missing_file(self):
        self.v2_finish()
        os.remove(os.path.join(self.wf, V2_PIECE, "review.md"))
        self.assertIn("review.md 없음", self.inspect())

    def test_empty_section(self):
        self.v2_finish(plan=V2_PLAN.replace("- `rg x` → 3\n", "<!-- 잰 것 -->\n- <명령> → <결과>\n"))
        self.assertIn("plan.md `## 잰 코드 사실`이 비었다", self.inspect())

    def test_missing_section(self):
        self.v2_finish(retro=V2_RETRO.replace("## 어긋난 것\n\n- 없음\n\n", ""))
        self.assertIn("retro.md `## 어긋난 것`이 비었다", self.inspect())

    def test_critical_without_test(self):
        self.v2_finish(review=V2_REVIEW.replace("| Important | 고침 abc1234 | test_edge |", "| Critical | 고침 abc1234 | — |"))
        self.assertTrue(any("review.md 반영 1: Critical인데 '시험' 칸이 비었다" in x for x in self.inspect()))

    def test_unknown_grade(self):
        self.v2_finish(review=V2_REVIEW.replace("| Minor |", "| 낮음 |"))
        self.assertTrue(any("review.md 반영 2: 등급 '낮음'" in x for x in self.inspect()))

    def test_review_table_needs_columns(self):
        self.v2_finish(review=V2_REVIEW.replace(TABLE, "| # | 지적 | 한 일 |\n| --- | --- | --- |\n"))
        self.assertIn("review.md `## 반영`에 '| # | 지적 | 출처 | 등급 | 한 일 | 시험 |' 대조표가 없다", self.inspect())

    def test_verify_line(self):
        self.v2_finish(retro=V2_RETRO.replace("- python3 -m unittest → OK\n", "- 돌림\n"))
        self.assertIn("retro.md `## 끝 검증`에 '- <명령> → <결과>' 줄이 없다", self.inspect())

    def test_head_needs_seam_flow(self):
        self.put(f"{V2_PIECE}/requirements.md", V2_REQ.replace("흐름: seam", "흐름: x"))
        self.v2_finish()
        self.assertIn("requirements.md 머리에 '흐름: seam' 없음", self.inspect())

    def test_missing_step(self):
        self.v2_finish()
        self.git("commit", "-q", "--amend", "-m", "P-061 끝: x")  # done 제목을 지움
        self.assertIn("빠진 단계: done — 커밋 제목 'P-061 <단계>: …'(빈 커밋으로 채울 수 있음)", self.inspect())

    def test_decision_out_of_range(self):
        self.put("decisions/0551-x.md", "# 0551\n\n작업: P-061\n")
        self.v2_finish()
        self.assertIn("결정 0551-x.md가 요구사항 범위 0611~0620 밖", self.inspect())

    def test_carryover_problems_are_included(self):
        self.v2_finish(retro=V2_RETRO.replace("- gateway: 대조 대상 옮기기\n", "- gateway: 옮기기 [C-009]\n"))
        self.assertTrue(any(x.startswith("check_carryover: ") and "C-009가 장부에 없다" in x for x in self.inspect()))

    def test_raw_templates_fail(self):
        """틀을 그대로 두면 끝 확인이 막는다 — 자리표(`<…>`)만 남은 줄은 채운 줄이 아니다."""
        self.v2_finish()
        skill = os.path.join(config.PLUGIN_ROOT, "src", "skills", "seam", "templates")
        for name in ("plan.md", "review.md", "retro.md"):
            self.put(f"{V2_PIECE}/{name}", read(os.path.join(skill, name)))
        req = read(os.path.join(skill, "requirements.md")).replace("<작업 ID>", V2)
        self.put(f"{V2_PIECE}/requirements.md", req)
        p = self.inspect()
        for want in ("requirements.md `## 문제`이 비었다", "requirements.md `## 요구`이 비었다", "plan.md `## 잰 코드 사실`이 비었다",
                     "plan.md `## 결정`이 비었다", "plan.md `## 할 일`이 비었다", "plan.md `## 코드 전 검토`이 비었다",
                     "review.md `## 동작`이 비었다", "retro.md `## 끝 검증`이 비었다",
                     "retro.md `## 끝 검증`에 '- <명령> → <결과>' 줄이 없다"):
            self.assertIn(want, p)

    def test_code_span_with_angle_brackets_is_content(self):
        self.v2_finish(plan=V2_PLAN.replace("- `rg x` → 3\n", "- `grep -c 'Map<K, V>'` → 3\n"))
        self.assertEqual(self.inspect(), [])

    def test_bad_args(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(inspect_cmd.main(["W-010"], self.ctx), 2)


if __name__ == "__main__":
    unittest.main()
