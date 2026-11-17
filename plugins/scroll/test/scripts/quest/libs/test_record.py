"""quest/libs/record.py 시험 — 합치기 기록 커밋(작업 목록 끝·장부 번호), 바뀐 규칙 문장 읽기."""
import copy
import os
from unittest import mock

from test import helpers as testing
from quest.commands import merge as m
from quest.libs import record
from test.scripts.quest.commands.test_merge import Repo  # 바탕(픽스처)


WF = "svc/.agents/workflow"


README = "# 작업\n\n## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n| {work} | t | 진행 | 0771~0780 |\n"


LEDGER = ("# 장부\n\n| ID | 출처 | 받는 쪽 | 내용 | 상태 | 근거 |\n| --- | --- | --- | --- | --- | --- |\n"
          "| C-010 | Q-001 | lead | 옛 일 | 열림 | - |\n\n## 뒤\n")


RETRO = "# 회고\n\n## 끝 검증\n\n- python3 → OK\n\n## 닫을 장부 줄\n\n- 없음\n\n## 넘길 일\n\n{items}"


def config_with(**sections):
    data = copy.deepcopy(testing.SVC)
    for key, value in sections.items():
        data[key] = value
    return data


class RecordTest(Repo):
    """리드가 합칠 때 작업 목록 `끝`과 넘길 일 장부 번호를 기록 커밋 하나로."""

    def test_record_texts(self):
        cfg = testing.make()
        readme, ledger, retro, ids = record.record_texts(
            "Q-077", "abc123456", README.format(work="Q-077"), LEDGER,
            RETRO.format(items="- gateway: 대조 대상 `a|b` 옮기기\n- lead: x [C-010]\n- 없음 말고\n"), cfg)
        self.assertIn("| Q-077 | t | 끝(abc123456, 로컬) | 0771~0780 |", readme)
        self.assertEqual(ids, ["C-011"])
        self.assertIn("| C-010 | Q-001 | lead | 옛 일 | 열림 | - |\n| C-011 | Q-077 | gateway | 대조 대상 `a\\|b` 옮기기 | 열림 | - |\n", ledger)
        self.assertTrue(ledger.endswith("\n\n## 뒤\n"))
        self.assertIn("- gateway: 대조 대상 `a|b` 옮기기 [C-011]\n- lead: x [C-010]\n", retro)

    def test_record_texts_again_changes_nothing(self):
        cfg = testing.make()
        first = record.record_texts("Q-077", "abc123456", README.format(work="Q-077"), LEDGER,
                               RETRO.format(items="- gateway: x\n- lead: y\n"), cfg)
        self.assertEqual(first[3], ["C-011", "C-012"])
        self.assertEqual(record.record_texts("Q-077", "zzz", *first[:3], cfg), (*first[:3], []))

    def test_first_row_goes_right_under_table_head(self):
        """장부 줄이 아직 없으면 표 머리 바로 뒤에 붙인다(빈 줄 뒤에 붙으면 표가 끊긴다)."""
        empty = "# 장부\n\n| ID | 출처 | 받는 쪽 | 내용 | 상태 | 근거 |\n| --- | --- | --- | --- | --- | --- |\n"
        _, ledger, _, ids = record.record_texts("Q-077", "abc", README.format(work="Q-077"), empty,
                                           RETRO.format(items="- lead: y\n"), testing.make())
        self.assertEqual(ids, ["C-001"])
        self.assertEqual(ledger, empty + "| C-001 | Q-077 | lead | y | 열림 | - |\n")

    def test_carry_prefix_is_fixed(self):
        """장부 ID 머리글자는 고정 `C` — 설정으로 바꾸던 키(carryover.id_prefix)는 모르는 키로 멈춘다."""
        _, ledger, retro, ids = record.record_texts("Q-077", "abc", README.format(work="Q-077"), LEDGER,
                                               RETRO.format(items="- lead: y\n"), testing.make())
        self.assertEqual(ids, ["C-011"])
        self.assertIn("- lead: y [C-011]", retro)
        with self.assertRaises(testing.config.ConfigError) as e:
            testing.make(config_with(carryover={"id_prefix": "H"}))
        self.assertIn("모르는 키: carryover.id_prefix — 받지 않는다 — 고정(`C`)", str(e.exception))

    def test_close_rows(self):
        """회고 `## 닫을 장부 줄`을 읽어 장부의 그 줄 상태·근거 칸을 고친다 — 다시 불러도 같다."""
        ledger = LEDGER.replace("| 열림 | - |\n", "| 열림 | - |\n| C-011 | Q-001 | lead | 일 | 요구사항 Q-077 | - |\n"
                                "| C-012 | Q-001 | gw | 이 | 요구사항 Q-077 | - |\n")
        retro = RETRO.format(items="- 없음\n").replace("## 닫을 장부 줄\n\n- 없음\n",
                                                       "## 닫을 장부 줄\n\n- C-011: 끝 — Q-077 a|b\n- C-012: 열림 — Q-077 넘김 — 범위 밖\n")
        new, closed = record.close_rows("Q-077", ledger, retro, testing.make())
        self.assertEqual(closed, ["C-011", "C-012"])
        self.assertIn("| C-011 | Q-001 | lead | 일 | 끝 | Q-077 a\\|b |\n| C-012 | Q-001 | gw | 이 | 열림 | Q-077 넘김 — 범위 밖 |\n", new)
        self.assertTrue(new.endswith("\n\n## 뒤\n"))
        self.assertEqual(record.close_rows("Q-077", new, retro, testing.make()), (new, []))

    def test_close_rows_stops_when_unreadable_or_left(self):
        ledger = LEDGER.replace("| 열림 | - |\n", "| 열림 | - |\n| C-011 | Q-001 | lead | 일 | 요구사항 Q-077 | - |\n")
        cfg = testing.make()
        cases = {
            "절 없음": RETRO.format(items="- 없음\n").replace("## 닫을 장부 줄\n\n- 없음\n\n", ""),
            "줄 빠짐": RETRO.format(items="- 없음\n"),
            "꼴 틀림": RETRO.format(items="- 없음\n").replace("## 닫을 장부 줄\n\n- 없음\n", "## 닫을 장부 줄\n\n- C-011 끝\n"),
            "없는 줄": RETRO.format(items="- 없음\n").replace("## 닫을 장부 줄\n\n- 없음\n",
                                                          "## 닫을 장부 줄\n\n- C-011: 끝 — a\n- C-099: 끝 — a\n"),
            "남의 줄": RETRO.format(items="- 없음\n").replace("## 닫을 장부 줄\n\n- 없음\n",
                                                          "## 닫을 장부 줄\n\n- C-011: 끝 — a\n- C-010: 끝 — a\n"),
        }
        for name, retro in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(record.RecordError):
                    record.close_rows("Q-077", ledger, retro, cfg)

    def test_merge_closes_ledger_rows(self):
        """합치기 기록 커밋이 장부 줄을 닫고, 통합 브랜치 장부에 `요구사항 Q-077` 줄이 남지 않는다."""
        ledger = os.path.join(self.top, WF, "quests", "carryover.md")
        with open(ledger, encoding="utf-8") as f:
            text = f.read()
        with open(ledger, "w", encoding="utf-8") as f:
            f.write(text.replace("| 열림 | - |\n", "| 열림 | - |\n| C-005 | Q-001 | lead | 일 | 요구사항 Q-077 | - |\n"))
        self.git(self.top, "commit", "-qam", "lead: 장부")
        self.git(self.wt, "rebase", "-q", "dev/main")
        with open(self.retro, encoding="utf-8") as f:
            text = f.read()
        with open(self.retro, "w", encoding="utf-8") as f:
            f.write(text.replace("## 닫을 장부 줄\n\n- 없음\n", "## 닫을 장부 줄\n\n- C-005: 버림 — 과잉\n"))
        self.git(self.wt, "commit", "-qam", "Q-077 done: 닫을 줄")
        code, out = self.main("Q-077", "--keep")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.head_subject(), "Q-077 merge: README 끝·넘길 일 C-011·C-012·장부 닫음 C-005")
        with open(ledger, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| C-005 | Q-001 | lead | 일 | 버림 | 과잉 |", text)
        self.assertNotIn("요구사항 Q-077", text)

    def test_merge_stops_before_merge_when_close_lines_unreadable(self):
        with open(self.retro, encoding="utf-8") as f:
            text = f.read()
        with open(self.retro, "w", encoding="utf-8") as f:
            f.write(text.replace("## 닫을 장부 줄\n\n- 없음\n\n", ""))
        self.git(self.wt, "commit", "-qam", "Q-077 done: 절 없음")
        code, _ = self.main("Q-077", "--keep")
        self.assertIn("합치기 전", str(code))
        self.assertIn("## 닫을 장부 줄", str(code))
        self.assertEqual(self.head_subject(), "base")

    def test_merge_writes_record_commit_then_ff(self):
        done = self.git(self.wt, "rev-parse", "HEAD")[:7]  # 짧은 해시는 한 길이(7) — libs/git.py SHORT
        code, out = self.main("Q-077", "--keep", "--verified", "손으로 봄")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.head_subject(), "Q-077 merge: README 끝·넘길 일 C-011·C-012")
        self.assertEqual(self.git(self.top, "log", "-1", "--format=%b", "dev/main"), "메모: 손으로 봄")
        with open(os.path.join(self.top, WF, "quests", "README.md"), encoding="utf-8") as f:
            self.assertIn(f"| Q-077 | t | 끝({done}, 로컬) | 0771~0780 |", f.read())
        with open(os.path.join(self.top, WF, "quests", "carryover.md"), encoding="utf-8") as f:
            self.assertIn("| C-012 | Q-077 | lead | 끝 검사에서 전체 검사 | 열림 | - |", f.read())
        self.assertEqual(self.git(self.wt, "status", "--porcelain"), "")

    def test_quest_check_runs_again_after_record(self):
        calls = []

        def check(wt, work):
            calls.append(self.git(wt, "log", "-1", "--format=%s"))
            return None if len(calls) == 1 else "quest_check end가 통과하지 않는다: 장부 줄 꼴"
        with mock.patch.object(m, "quest_check_problem", check):
            code = self.main("Q-077", "--keep")[0]
        self.assertIn("장부 줄 꼴", str(code))
        self.assertEqual(calls, ["Q-077 done: x", "Q-077 merge: README 끝·넘길 일 C-011·C-012"])
        self.assertEqual(self.head_subject(), "base")


if __name__ == "__main__":
    unittest.main()
