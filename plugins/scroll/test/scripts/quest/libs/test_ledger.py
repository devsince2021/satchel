"""quest/libs/ledger.py 시험 — 넘길 일 장부·작업 번호 확인. 자리는 시험 설정(기록 `quests/`)."""
import tempfile
import unittest
from pathlib import Path

from test import helpers as testing
from quest.libs.ledger import check as _check


CFG = testing.make({"branches": {"integration": "main"}, "quest": {"quests": "quests"}, "session": {"terminal": "none"}})


def check(d):
    return _check(d, CFG)


README = "# workflow\n\n## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n{rows}"


LEDGER = "| ID | 출처 | 받는 쪽 | 내용 | 상태 | 근거 |\n| --- | --- | --- | --- | --- | --- |\n{rows}"


class CheckCarryoverTest(unittest.TestCase):
    """아는 번호는 README 작업 목록 줄과 `quests/Q-NNN-*/requirements.md`. 옛 자리
    (`requirements/`·`retrospec/`·`tasks/plans` 장부)·짧은 흐름·end 표식은 보지 않는다."""

    def make(self, ids=("001", "002"), status="끝", retro="## 넘길 일\n\n- gateway: 옮기기 [C-001]\n",
             ledger_rows="| C-001 | Q-001 | gateway | 옮기기 | 열림 | — |\n", listed=None):
        """README 줄만 있는 옛 번호(ids)와, 회고를 든 quest Q-001이 아닌 — Q-00X 회고는 quest `Q-0NN`으로 둔다."""
        d = Path(tempfile.mkdtemp())
        (d / "quests").mkdir()
        listed = ids if listed is None else listed
        (d / "quests" / "README.md").write_text(README.format(rows="".join(f"| Q-{n} | x | {status} | — |\n" for n in listed)))
        (d / "quests" / "carryover.md").write_text(LEDGER.format(rows=ledger_rows))
        if retro is not None:
            self.quest(d, "001", retro=retro, line=False)
        return d

    def quest(self, d, n, retro=None, req=None, line=True, status="끝(abc, 로컬)"):
        folder = d / "quests" / f"Q-{n}-x"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "requirements.md").write_text(req or f"# Q-{n}\n\n- 작업: Q-{n} · 결정 번호: 0541~0550 · 흐름: quest\n")
        if retro is not None:
            (folder / "retro.md").write_text(retro)
        if line:
            readme = d / "quests" / "README.md"
            readme.write_text(readme.read_text() + f"| Q-{n} | x | {status} | — |\n")
        return folder

    def test_clean(self):
        self.assertEqual(check(self.make()), [])

    def test_item_without_tag(self):
        p = check(self.make(retro="## 넘길 일\n\n- gateway: 옮기기\n"))
        self.assertTrue(any("[C-NNN]이 없다" in x for x in p), p)

    def test_none_item_is_fine(self):
        self.assertEqual(check(self.make(retro="## 넘길 일\n\n- 없음.\n")), [])

    def test_tag_missing_in_ledger(self):
        p = check(self.make(retro="## 넘길 일\n\n- x [C-009]\n"))
        self.assertTrue(any("C-009가 장부에 없다" in x for x in p), p)

    def test_reserved_id_in_prose(self):
        p = check(self.make(retro="## 넘길 일\n\n- Q-005: 나중에 [C-001]\n"))
        self.assertTrue(any("Q-005가 작업 목록에도 quests/에도 없다" in x for x in p), p)

    def test_gap_in_numbers(self):
        p = check(self.make(ids=("001", "003")))
        self.assertTrue(any("Q-002이 비었다" in x for x in p), p)

    def test_quest_number_without_readme_line(self):
        d = self.make()
        self.quest(d, "003", line=False)
        self.assertTrue(any("작업 목록에 Q-003 줄이 없다" in x for x in check(d)))

    # ---- README 작업 목록 줄이 옛 번호의 근거다 — 옛 요구사항 파일은 지웠다 ----

    def test_readme_line_alone_is_a_known_number(self):
        """옛 작업은 README 줄만 남는다 — 문서·빈 번호·장부 상태에서 아는 번호."""
        d = self.make(ids=("001", "002", "003"), ledger_rows="| C-001 | Q-002 | lead | x | 요구사항 Q-002 | — |\n",
                      retro="## 넘길 일\n\n- lead: Q-003에서 받음 [C-001]\n")
        self.assertFalse((d / "requirements").exists())
        self.assertEqual(check(d), [])

    def test_old_record_folders_are_not_read(self):
        """`requirements/`·`retrospec/`·`tasks/plans` 장부가 남아 있어도 읽지 않는다(지운 자리)."""
        d = self.make(ids=tuple(f"{k:03d}" for k in range(1, 11)))
        (d / "requirements").mkdir()
        (d / "requirements" / "Q-011-x.md").write_text("# Q-011\n\nQ-099\n")
        (d / "retrospec").mkdir()
        (d / "retrospec" / "Q-002-x.md").write_text("# 회고\n\n아무 글\nQ-098\n")
        self.assertEqual(check(d), [])

    def test_done_old_work_needs_no_end_mark_or_retro(self):
        """README `끝`이고 quests 폴더가 없는 번호(옛 작업)는 끝 판정을 하지 않는다 — end 표식·짧은 흐름 갈래 없음."""
        p = check(self.make(ids=tuple(f"{k:03d}" for k in range(1, 26))))
        self.assertFalse(any("end 표식" in x or "짧은 흐름" in x for x in p), p)
        self.assertEqual(p, [])

    def test_status_points_to_unknown_number(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | lead | x | 요구사항 Q-004 | — |\n"))
        self.assertTrue(any("C-001: 상태의 Q-004가 작업 목록에도 quests/에도 없다" in x for x in p), p)

    def test_status_points_to_quest_requirement(self):
        d = self.make(ledger_rows="| C-001 | Q-001 | lead | x | 요구사항 Q-003 | — |\n")
        self.quest(d, "003", retro="## 넘길 일\n\n- 없음\n")
        self.assertEqual(check(d), [])

    def test_readme_missing_is_a_problem(self):
        """README가 옛 번호의 근거다 — 읽지 못하면 조용히 통과하지 않는다."""
        d = Path(tempfile.mkdtemp())
        (d / "quests").mkdir()
        (d / "quests" / "carryover.md").write_text(LEDGER.format(rows=""))
        self.assertIn("quests/README.md가 없다", check(d))

    def test_readme_without_list_section_is_a_problem(self):
        d = self.make()
        (d / "quests" / "README.md").write_text("# workflow\n\n## 작업 목록 표\n\n| Q-001 | x | 끝 | — |\n")
        self.assertIn("quests/README.md에 '## 작업 목록' 절이 없다", check(d))

    def test_quest_folder_without_requirements(self):
        """retro.md만 있는 quests 폴더도 빠뜨리지 않는다."""
        d = self.make()
        folder = d / "quests" / "Q-002-x"
        folder.mkdir(parents=True)
        (folder / "retro.md").write_text("# 회고\n")
        self.assertIn("quests/Q-002-x: requirements.md가 없다", check(d))

    def test_same_number_in_two_quest_folders(self):
        """한 번호는 quests 폴더 하나."""
        d = self.make()
        self.quest(d, "003", retro="## 넘길 일\n\n- 없음\n")
        (d / "quests" / "Q-003-y").mkdir()
        (d / "quests" / "Q-003-y" / "requirements.md").write_text("# Q-003\n")
        self.assertIn("Q-003: quests 폴더가 둘 이상이다(Q-003-x, Q-003-y)", check(d))

    def test_gap_below_quest_number_is_caught(self):
        d = self.make(ids=("001",))
        self.quest(d, "003", retro="## 넘길 일\n\n- 없음\n")
        p = check(d)
        self.assertTrue(any("Q-002이 비었다" in x for x in p), p)

    def test_sent_without_evidence(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | devops | x | 넘김 | 회고에 적음 |\n"))
        self.assertTrue(any("C-001: 넘김인데 보낸 근거 없음" in x for x in p), p)

    def test_sent_with_msg_id(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | devops | x | 넘김 | msg fd54b60b |\n"))
        self.assertEqual(p, [])

    def test_sent_with_time_and_address(self):
        for ev in ("2026-11-08 01:1x devops-lead에 SendMessage", "2026-11-08T13:06 SendMessage(to: devops)"):
            p = check(self.make(ledger_rows=f"| C-001 | Q-001 | devops | x | 넘김 | {ev} |\n"))
            self.assertEqual(p, [], ev)

    def test_sent_time_without_address(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | devops | x | 넘김 | 2026-11-08 01:10 보냄 |\n"))
        self.assertTrue(any("넘김인데 보낸 근거 없음" in x for x in p), p)

    def test_broken_row_cell_count(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | devops | x | 넘김26-11-07 보냄 |\n"))
        self.assertTrue(any("C-001: 장부 줄 꼴이 깨짐(칸 5개)" in x for x in p), p)

    def test_status_not_a_word(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | devops | x | 보류 | — |\n"))
        self.assertTrue(any("C-001: 상태 낱말이 아님" in x for x in p), p)

    def test_escaped_pipe_in_cell(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | a | x \\| y | 열림 | — |\n"))
        self.assertEqual(p, [])

    def test_address_word_boundary(self):
        p = check(self.make(ledger_rows="| C-001 | Q-001 | x | y | 넘김 | 2026-11-08 01:10 /home/SendMessage/workspaces |\n"))
        self.assertTrue(any("넘김인데 보낸 근거 없음" in x for x in p), p)

    def test_bad_id_shape(self):
        p = check(self.make(ledger_rows="| C-1 | Q-001 | x | y | 열림 | — |\n"))
        self.assertTrue(any("C-1: ID 꼴" in x for x in p), p)

    def test_duplicate_id(self):
        row = "| C-001 | Q-001 | x | y | 열림 | — |\n"
        p = check(self.make(ledger_rows=row + row))
        self.assertTrue(any("C-001: 중복" in x for x in p), p)

    def test_no_readme(self):
        d = self.make()
        (d / "quests" / "README.md").unlink()
        self.assertTrue(any("작업 목록에 Q-001 줄이 없다" in x for x in check(d)))

    def test_readme_without_list_section(self):
        d = self.make()
        (d / "quests" / "README.md").write_text("# workflow\n")
        self.assertTrue(any("작업 목록에 Q-001 줄이 없다" in x for x in check(d)))

    def test_other_sections_ignored(self):
        self.assertEqual(check(self.make(retro="## 다음에 바꿀 것\n\n- 아무 말\n\n## 넘길 일\n\n- 없음\n")), [])

    # ---- 꼴 경계 ----

    def test_reserved_id_followed_by_korean_particle(self):
        for prose, n in (("Q-011부터 한다", "011"), ("Q-014에서 받는다", "014"), ("Q-002·Q-003을 예고", "003")):
            p = check(self.make(retro=f"## 넘길 일\n\n- lead: {prose} [C-001]\n"))
            self.assertTrue(any(f"Q-{n}가 작업 목록에도 quests/에도 없다" in x for x in p), (prose, p))

    def test_id_inside_other_word_is_not_work_id(self):
        p = check(self.make(retro="## 넘길 일\n\n- lead: XQ-005·Q-0051 값 [C-001]\n"))
        self.assertEqual(p, [])

    def test_star_and_numbered_items_need_tag(self):
        for item in ("* gateway: 옮기기", "1. gateway: 옮기기", "  - 하위 일"):
            p = check(self.make(retro=f"## 넘길 일\n\n- gateway: 옮기기 [C-001]\n{item}\n"))
            self.assertTrue(any("[C-NNN]이 없다" in x for x in p), (item, p))

    def test_star_and_numbered_none_items_are_fine(self):
        for item in ("* 없음", "1. 없음"):
            self.assertEqual(check(self.make(retro=f"## 넘길 일\n\n{item}\n")), [], item)

    def test_retro_needs_carryover_section(self):
        for retro in ("## 다음에 바꿀 것\n\n- x\n", "## 넘길일\n\n- gateway [C-001]\n"):
            p = check(self.make(retro=retro))
            self.assertTrue(any("Q-001-x/retro.md: '## 넘길 일' 절이 없다" in x for x in p), (retro, p))

    def test_retro_carryover_section_needs_an_item(self):
        p = check(self.make(retro="## 넘길 일\n\n아무 글\n"))
        self.assertTrue(any("Q-001-x/retro.md: '## 넘길 일'에 항목이 없다" in x for x in p), p)

    # ---- quest 흐름: quests/Q-NNN-<슬러그>/ ----

    def test_quest_retro_item_needs_tag(self):
        d = self.make()
        self.quest(d, "003", retro="## 넘길 일\n\n- gateway: 옮기기\n")
        p = check(d)
        self.assertTrue(any("Q-003-x/retro.md: 넘길 일 항목에 [C-NNN]이 없다" in x for x in p), p)

    def test_quest_retro_tag_missing_in_ledger(self):
        d = self.make()
        self.quest(d, "003", retro="## 넘길 일\n\n- x [C-009]\n")
        self.assertTrue(any("Q-003-x/retro.md: C-009가 장부에 없다" in x for x in check(d)))

    def test_quest_docs_reserved_id(self):
        d = self.make()
        folder = self.quest(d, "003", retro="## 넘길 일\n\n- 없음\n")
        (folder / "plan.md").write_text("# 계획\n\nQ-009에서 이어 한다\n")
        self.assertTrue(any("plan.md: Q-009가 작업 목록에도 quests/에도 없다" in x for x in check(d)))

    def test_done_quest_needs_retro(self):
        d = self.make(ids=tuple(f"{k:03d}" for k in range(1, 10)))
        self.quest(d, "010")
        p = check(d)
        self.assertTrue(any("Q-010: 끝인데 quests/Q-010-x/retro.md가 없다" in x for x in p), p)

    def test_open_quest_needs_no_retro(self):
        d = self.make()
        self.quest(d, "003", status="진행")
        self.assertEqual(check(d), [])

    # ---- 넘길 일 번호는 리드가 합칠 때(README `끝`) 받는다 — 판 가르기 없음 ----

    def untagged_quest(self, n, status):
        d = self.make()
        req = f"# Q-{n}\n\n- 작업: Q-{n} · 결정 번호: 0611~0620 · 흐름: quest\n"
        self.quest(d, n, retro="## 넘길 일\n\n- gateway: 옮기기\n", req=req, status=status)
        return check(d)

    def test_untagged_item_ok_while_in_progress(self):
        p = self.untagged_quest("003", "진행")
        self.assertFalse(any("[C-NNN]이 없다" in x for x in p), p)

    def test_untagged_item_blocked_after_merge(self):
        p = self.untagged_quest("003", "끝(abc, 로컬)")
        self.assertTrue(any("Q-003-x/retro.md: 넘길 일 항목에 [C-NNN]이 없다" in x for x in p), p)

    def test_tag_still_checked_in_ledger_while_in_progress(self):
        d = self.make()
        self.quest(d, "003", retro="## 넘길 일\n\n- gateway: x [C-009]\n", status="진행")
        self.assertTrue(any("Q-003-x/retro.md: C-009가 장부에 없다" in x for x in check(d)))


if __name__ == "__main__":
    unittest.main()
