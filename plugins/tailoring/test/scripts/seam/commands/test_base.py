"""seam/commands/base.py 시험 — 작업 범위 기준 커밋."""
import io
import unittest
from contextlib import redirect_stdout

from seam.commands import base as base_cmd
from seam.libs import commits
from seam.libs.checks import rules
from test.scripts.seam.libs.test_checks import Base, tearDownModule  # 바탕(픽스처)


def at(hour):
    return f"2026-11-01T{hour:02d}:00:00+00:00"


V2_REQ = ("# t\n\n- 작업: P-061 · 결정 번호: 0611~0620 · 브랜치: piece/P-061-sample · 흐름: seam\n"
          "- 날짜: 2026-11-12 · 요청: 사용자 · 대상: guard\n- 출발: 시험\n\n"
          "## 문제\n\n- 어긋남\n\n## 요구\n\n- R1. 하나\n\n## 범위\n\n- 안: x\n\n## 수용 기준\n\n- 시험 OK\n")


class WorkBaseTest(Base):
    """작업 범위 기준은 merge-base(dev/main)·merge-base(origin/dev/main)·요구사항 커밋 부모 가운데
    다른 것을 모두 품은 가장 가까운 것. 로컬 dev/main이 낡아도 남의 커밋을 섞지 않는다."""

    def setUp(self):
        super().setUp()  # R: P-061 req(뿌리), dev/main = R
        self.touch(".agents/rules/other.md")
        self.commit("P-060 run: 남의 작업(규칙 문서)", at(1))
        self.x = self.git("rev-parse", "HEAD").strip()
        self.put("pieces/P-062-next/requirements.md", V2_REQ.replace("P-061", "P-062"))
        self.commit("P-062 req: 요구사항", at(2))
        self.q = self.git("rev-parse", "HEAD").strip()
        self.commit("P-062 plan: x", at(3))

    def test_stale_tech_main_falls_back_to_requirements_parent(self):
        self.assertEqual(commits.work_base(self.ctx, "P-062"), self.x)
        self.assertEqual(rules.changed_rule_docs(self.ctx, "P-062"), [])

    def test_newer_origin_tech_main_wins(self):
        self.git("update-ref", "refs/remotes/origin/dev/main", self.q)
        self.assertEqual(commits.work_base(self.ctx, "P-062"), self.q)

    def test_rebased_on_newer_tech_main(self):
        self.git("branch", "-f", "dev/main", "HEAD")
        self.touch("x.md")
        self.commit("P-062 run: #1 x", at(4))
        self.assertEqual(commits.work_base(self.ctx, "P-062"), self.git("rev-parse", "dev/main").strip())

    def test_base_command_prints_sha(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = base_cmd.main(["P-062"], self.ctx)
        self.assertEqual((code, out.getvalue().strip()), (0, self.x))

    def test_no_requirements_commit_keeps_tech_main(self):
        self.assertEqual(commits.work_base(self.ctx, "P-099"), self.git("rev-parse", "dev/main").strip())


if __name__ == "__main__":
    unittest.main()
