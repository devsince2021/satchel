"""quest/commands/status.py 시험 — 단계·첫 시각, 빠진 필수 단계."""
import io
import unittest
from contextlib import redirect_stdout

from quest.commands import status as status_cmd
from quest.libs import commits
from test.scripts.quest.libs.test_checks import Base, tearDownModule  # 바탕(픽스처)


def at(hour):
    return f"2026-11-01T{hour:02d}:00:00+00:00"


V2 = "Q-061"


class StatusTest(Base):
    def test_steps_from_titles_and_missing(self):
        for hour, step in enumerate(("plan", "run", "review", "done"), 1):
            self.commit(f"Q-061 {step}: x", at(hour))
        found = commits.steps_of(self.ctx, V2)
        self.assertEqual([s for s, _ in found], ["req", "plan", "run", "review", "done"])
        self.assertEqual(commits.missing(found), ["plan-review"])

    def test_plan_review_is_not_plan(self):
        self.commit("Q-061 plan-review: x", at(1))
        self.assertEqual([s for s, _ in commits.steps_of(self.ctx, V2)], ["req", "plan-review"])

    def test_other_work_and_free_titles_ignored(self):
        self.commit("Q-062 plan: x", at(1))
        self.commit("Q-061 계획: x", at(2))
        self.assertEqual([s for s, _ in commits.steps_of(self.ctx, V2)], ["req"])

    def test_empty_step_commit_counts(self):
        """빈 단계 커밋(`--allow-empty`)도 단계로 센다."""
        self.commit("Q-061 plan-review: 빈 단계", at(1))
        self.assertIn("plan-review", [s for s, _ in commits.steps_of(self.ctx, V2)])

    def test_main_status_prints(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = status_cmd.main([V2], self.ctx)
        self.assertEqual(code, 0)
        self.assertIn("빠진 단계: plan, plan-review, run, review, done", out.getvalue())


if __name__ == "__main__":
    unittest.main()
