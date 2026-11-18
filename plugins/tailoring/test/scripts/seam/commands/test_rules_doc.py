"""seam/commands/rules_doc.py 시험 — 생성 구역 견주기·잘못 부름."""
import unittest


from test import helpers as testing
from test.scripts.seam.test_main import Repo  # 바탕(픽스처)


class RulesDocCommandTest(Repo):
    """부명령 rules-doc."""

    def test_rules_doc(self):
        """생성 구역은 이미 만들어져 있다 — `--check`는 0. 어느 자리에서 불러도 플러그인 문서만 본다. 모르는 인자는 2."""
        code, out, _ = self.seam("rules-doc", "--check")
        self.assertEqual((code, out), (0, "rules-doc: 생성 구역이 flow.json과 같다\n"))
        code, out, _ = self.seam("rules-doc", "--write")
        self.assertEqual((code, out), (2, f"쓰는 법: python3 {testing.SEAM} rules-doc [--check]\n"))


if __name__ == "__main__":
    unittest.main()
