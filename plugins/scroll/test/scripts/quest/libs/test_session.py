"""quest/libs/session.py 시험 — 작업 세션 가르기(작업 브랜치 + 세션 기록)."""
import json
import os
import subprocess
import unittest

from quest.libs import session
from test.scripts.quest.commands.test_guard import WorkSession  # 바탕(픽스처)


GLOB_DOTDOT = "cat $P/domain/src/main/java/*/../ -h; find …; grep …"  # 하위 에이전트가 확인 창에 멈추던 꼴


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout


class SessionTest(WorkSession):
    """작업 세션 가르기 — 작업 브랜치 + 세션 기록(워크트리가 이 저장소)."""

    def test_record_values(self):
        self.assertEqual(self.record["lead_top"], self.lead)
        self.assertEqual(os.path.realpath(self.record["worktree"]), self.wt)
        self.assertTrue(os.path.isfile(self.record["settings"]))
        self.assertEqual(self.record["block_git"], ["push", "checkout", "restore", "stash", "clean", "switch", "merge", "pull", "rebase", "am"])

    def test_not_work_sessions(self):
        self.assertIsNone(session.work_session(self.lead))  # 리드 체크아웃(통합 브랜치)
        self.assertIsNone(session.work_session(self.tmp))  # git 밖
        git(self.lead, "branch", "quest/Q-078-other")
        other = os.path.join(self.tmp, "other-wt")
        git(self.lead, "worktree", "add", "-q", other, "quest/Q-078-other")
        self.assertIsNone(session.work_session(other))  # 작업 브랜치지만 세션 기록 없음

    def test_moved_record_is_not_a_session(self):
        """합친 뒤(`done/`으로 옮김)나 다른 워크트리를 가리키는 기록은 작업 세션이 아니다."""
        rec = os.path.join(self.record["session_dir"], "session.json")
        with open(rec, encoding="utf-8") as f:
            data = json.load(f)
        data["worktree"] = os.path.join(self.tmp, "elsewhere")
        put(rec, json.dumps(data))
        self.assertIsNone(session.work_session(self.wt))
        os.remove(rec)
        self.assertIsNone(session.work_session(self.wt))

    def test_lead_checkout_passes_everything(self):
        """리드 세션(통합 브랜치)에서는 같은 명령이 모두 0 — 플러그인만 켠 다른 세션에 해가 없다."""
        for tool, inp in (("AskUserQuestion", {"questions": []}), ("Agent", {"prompt": "할 일: x"}),
                          ("Bash", {"command": f"git -C {self.wt} reset --hard"}), ("Bash", {"command": GLOB_DOTDOT}),
                          ("Bash", {"command": f"echo x > {self.wt}/.satchel/quest.json"})):
            self.assertEqual(self.run_hook(tool, cwd=self.lead, **inp), (0, ""), (tool, inp))


if __name__ == "__main__":
    unittest.main()
