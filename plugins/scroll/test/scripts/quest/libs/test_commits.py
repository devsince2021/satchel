"""quest/libs/commits.py 시험 — 묶음 커밋 제목의 단계 찾기."""
import unittest


from quest.libs import commits
from test.scripts.quest.libs.test_checks import Base, tearDownModule  # 바탕(픽스처)


def at(hour):
    return f"2026-11-01T{hour:02d}:00:00+00:00"


V2 = "Q-061"


class BundledTitleTest(Base):
    """C-576: 여러 작업을 묶은 req 커밋 제목도 각 작업의 req 단계로 센다."""

    def test_bundled_title_counts_for_each_work(self):
        self.commit("Q-060·Q-061·Q-062 plan: 묶음", at(1))
        self.assertEqual([s for s, _ in commits.steps_of(self.ctx, V2)], ["req", "plan"])

    def test_bundled_title_without_this_work_ignored(self):
        self.commit("Q-060·Q-062 plan: 다른 작업 묶음", at(1))
        self.commit("Q-0610 plan: 다른 번호", at(2))
        self.assertEqual([s for s, _ in commits.steps_of(self.ctx, V2)], ["req"])


if __name__ == "__main__":
    unittest.main()
