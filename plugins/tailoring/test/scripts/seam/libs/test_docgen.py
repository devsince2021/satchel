"""seam/libs/docgen.py 시험 — 생성 구역이 flow.json을 따라 바뀜, 표지 짝."""
import json
import os
import shutil
import tempfile
import unittest

from seam.libs import rules
from seam.libs import docgen as rules_doc


def flow_data():
    with open(rules.FLOW_FILE, encoding="utf-8") as f:
        return json.load(f)


def rename_step(data, old, new):
    """단계 이름 하나를 모든 자리(steps·order·reviews)에서 바꾼 사본."""
    text = json.dumps(data, ensure_ascii=False)
    return json.loads(text.replace(f'"{old}"', f'"{new}"'))


class DocgenTest(unittest.TestCase):
    """생성 구역 만들기."""

    def test_changed_flow_changes_docs(self):
        tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "flow.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rename_step(flow_data(), "run", "impl"), f, ensure_ascii=False)
        body = rules_doc.render(rules.load(path))
        self.assertIn("`<ID> impl: #N …`", body)
        self.assertNotIn("`run`", body)
        self.assertTrue(all(d for _, d in rules_doc.regenerate(write=False, flow=rules.load(path))))

    def test_markers_must_pair(self):
        with self.assertRaises(rules_doc.DocError):
            rules_doc.apply("앞\n" + rules_doc.BEGIN + "\n뒤\n", "몸", "x.md")
        text = f"앞\n{rules_doc.BEGIN}\n옛\n{rules_doc.END}\n뒤\n"
        self.assertEqual(rules_doc.apply(text, "새", "x.md"), f"앞\n{rules_doc.BEGIN}\n새\n{rules_doc.END}\n뒤\n")


if __name__ == "__main__":
    unittest.main()
