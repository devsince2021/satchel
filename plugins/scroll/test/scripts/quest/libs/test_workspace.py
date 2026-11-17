"""quest/libs/workspace.py 시험 — 작업 자리 셈(이름·브랜치·워크트리)과 열기 전 확인."""
import os
import unittest

from test import helpers as testing
from quest.libs import workspace
from test.scripts.quest.commands.test_open import Lead, svc_config  # 바탕(픽스처)


WF = "svc/.agents/workflow"


REQ = ("# t\n\n- 작업: Q-077 · 결정 번호: 0771~0780 · 브랜치: quest/Q-077-sample · 흐름: quest\n"
       "- 날짜: 2026-11-12 · 요청: 사용자 · 대상: guard\n- 출발: 시험\n\n"
       "## 문제\n\n- 어긋남\n\n## 요구\n\n- R1. 하나\n\n## 범위\n\n- 안: x\n\n## 수용 기준\n\n- 시험 OK\n")


README = "# 작업\n\n## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n| Q-077 | t | 진행 | 0771~0780 |\n"


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class PlanTest(Lead):
    def test_names_come_from_config(self):
        p = self.p
        self.assertEqual(p["branch"], "quest/Q-077-sample")
        self.assertEqual(p["worktree"], os.path.join(self.root, "lead-q-077"))
        self.assertEqual(p["session_dir"], os.path.join(self.top, ".git", "satchel", "quest-sessions", "Q-077"))
        self.assertEqual(p["requirements"], f"{WF}/quests/Q-077-sample/requirements.md")
        self.assertEqual(p["title"], "quest Q-077")

    def test_bad_id_and_missing_requirement(self):
        with self.assertRaises(SystemExit):
            workspace.plan("X-077", "x", self.top, self.cfg)
        with self.assertRaises(SystemExit):
            workspace.plan("Q-078", "x", self.top, self.cfg)


class CheckLeadTest(Lead):
    def test_clean(self):
        self.assertEqual(workspace.check_lead(self.p, self.cfg), [])

    def test_problems(self):
        put(os.path.join(self.top, WF, "quests", "README.md"), README.replace("| Q-077 |", "| Q-076 |"))
        put(os.path.join(self.top, WF, "quests", "Q-077-sample", "requirements.md"), REQ + "\n")
        self.git("checkout", "-q", "-b", "other")
        got = "\n".join(workspace.check_lead(dict(self.p, lead_name=" "), self.cfg))
        for want in ("리드 체크아웃이 dev/main가 아니다: other", f"커밋 안 한 변경이 있다: {WF}/quests/README.md",
                     f"커밋 안 한 변경이 있다: {WF}/quests/Q-077-sample/requirements.md", "작업 목록에 Q-077 줄이 없다",
                     "--lead <리드 세션 이름>이 없다"):
            self.assertIn(want, got)

    def test_config_must_be_committed(self):
        testing.write(self.top, svc_config(model="sonnet"))
        self.assertIn("커밋 안 한 변경이 있다: .satchel/quest.json", workspace.check_lead(self.p, self.cfg))

    def test_requirements_must_match_template(self):
        put(os.path.join(self.top, WF, "quests", "Q-077-sample", "requirements.md"), REQ.replace("- 출발: 시험\n", ""))
        self.git("commit", "-qam", "x")
        self.assertIn("요구사항이 틀에 맞지 않는다: 요구사항 머리에 틀의 칸 '출발:'이 없다", workspace.check_lead(self.p, self.cfg))

    def test_existing_branch_and_worktree(self):
        self.git("branch", "quest/Q-077-sample")
        os.makedirs(self.p["worktree"])
        got = workspace.check_lead(self.p, self.cfg)
        self.assertIn("브랜치가 이미 있다: quest/Q-077-sample", got)
        self.assertIn(f"워크트리 자리가 이미 있다: {self.p['worktree']}", got)


class WorktreePlaceTest(Lead):
    """작업 워크트리 자리(고정 `{parent}/{repo}-{id_lower}`)가 리드 저장소 안이면 열지 않는다 — `Edit(<리드>/**)`가 워크트리까지 덮는다."""

    def test_fixed_place_is_beside_lead(self):
        self.assertEqual(self.p["worktree"], os.path.join(self.root, "lead-q-077"))

    def test_same_place_and_symlink_inside(self):
        self.assertTrue(workspace.worktree_place_problems(dict(self.p, worktree=self.top)))
        link = os.path.join(self.root, "link")
        os.symlink(self.top, link)  # 밖으로 보이는 자리지만 실제로는 리드 저장소 안
        self.assertTrue(workspace.worktree_place_problems(dict(self.p, worktree=os.path.join(link, "wt"))))

    def test_outside_passes(self):
        self.assertEqual(workspace.worktree_place_problems(self.p), [])  # 기본값 — 리드 저장소 옆
        self.assertEqual(workspace.worktree_place_problems(dict(self.p, worktree=self.top + "-x")), [])  # 이름 머리만 같은 옆 자리


if __name__ == "__main__":
    unittest.main()
