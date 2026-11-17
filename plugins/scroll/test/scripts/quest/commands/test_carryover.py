"""quest/commands/carryover.py 시험 — 진짜 프로세스로 장부 확인 종료 코드."""
import tempfile
import unittest

from test.scripts.quest.test_main import Repo  # 바탕(픽스처)


class CarryoverCommandTest(Repo):
    """부명령 carryover."""

    def test_carryover(self):
        code, out, _ = self.quest("carryover")
        self.assertEqual(code, 1)
        self.assertIn(".agents/quests/README.md가 없다", out)
        self.assertTrue(out.endswith("check_carryover: 위반 3\n"), out)
        code, out, _ = self.quest("carryover", self.repo, cwd=tempfile.gettempdir())  # 뿌리를 인자로
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
