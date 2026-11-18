"""seam/libs/deny.py 시험 — 세션 settings deny(홈 deny 옮김·규칙 files·git·--open 폴더)."""
import json
import os
from unittest import mock

from test import helpers as testing
from seam.libs import deny as deny_lib
from seam.libs import workspace
from test.scripts.seam.commands.test_feed import Lead  # 바탕(픽스처)


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class SettingsTest(Lead):
    def test_deny_only_no_hook(self):
        """세션 settings에는 deny만 — Stop 훅은 플러그인 훅이 건다(또 넣으면 두 번 돌아 되돌림 횟수가 두 배)."""
        s = deny_lib.session_settings(self.p, self.cfg)
        deny, wt = s["permissions"]["deny"], self.p["worktree"]
        for want in (f"Edit(/{self.top}/**)", f"Edit(/{self.p['session_dir']}/**)", f"Edit(/{wt}/.studio/**)",
                     f"Edit(/{wt}/.agents/**)", "Bash(git push:*)", "Bash(git rebase:*)"):
            self.assertIn(want, deny)
        self.assertEqual(list(s), ["permissions"])
        self.assertNotIn("hooks", s)

    def test_ledger_denied(self):
        """장부(`<seam.pieces>/carryover.md`)는 리드만 쓴다 — 작업 세션 settings deny에 워크트리 장부를 싣는다."""
        deny = deny_lib.session_settings(self.p, self.cfg)["permissions"]["deny"]
        self.assertIn(f"Edit(/{self.p['worktree']}/{self.cfg.rel('carryover')})", deny)

    def test_missing_hook_file_is_a_problem(self):
        with mock.patch.object(workspace, "HOOKS_JSON", os.path.join(self.root, "없음.json")):
            self.assertIn(f"훅 파일이 없다: {os.path.join(self.root, '없음.json')}", workspace.check_lead(self.p, self.cfg))

    def test_guard_deny(self):
        """질문 창(훅이 안 걸려도), 플러그인 자리(훅을 고쳐 풀지 않게), 작업 세션 홈 settings.json."""
        deny = deny_lib.session_settings(self.p, self.cfg)["permissions"]["deny"]
        for want in ("AskUserQuestion", f"Edit(/{testing.PLUGIN}/**)", f"Edit(/{os.path.realpath(self.home)}/settings.json)"):
            self.assertIn(want, deny)

    def test_home_deny_moves_lead_paths_to_worktree(self):
        """홈 settings deny를 싣고 리드 체크아웃 경로는 워크트리 경로로 옮긴다."""
        put(os.path.join(self.home, "settings.json"), json.dumps({"permissions": {"deny": [
            f"Read(/{self.top}/secret/**)", f"Edit(/{self.top})", "Read(//elsewhere/x)"]}}))
        deny = deny_lib.session_settings(self.p, self.cfg)["permissions"]["deny"]
        wt = self.p["worktree"]
        for want in (f"Read(/{wt}/secret/**)", f"Edit(/{wt})", "Read(//elsewhere/x)"):
            self.assertIn(want, deny)
        self.assertNotIn(f"Read(/{self.top}/secret/**)", deny)

    def test_session_home_from_env(self):
        """작업 세션 홈은 여는 쪽 환경의 `CLAUDE_CONFIG_DIR`(없으면 `~/.claude`) — 설정으로 받지 않는다."""
        self.assertEqual(workspace.session_home(), os.path.realpath(self.home))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": os.path.join(self.root, "other")}):
            self.assertEqual(workspace.session_home(), os.path.join(self.root, "other"))


class OpenFolderTest(Lead):
    """`--open <폴더>`가 덮는 deny 항목을 빼고 형제를 하나씩 막는다 — glob 문자 클래스 없음."""

    def setUp(self):
        super().setUp()
        for f in (".agents/skills/token-pool/pool.py", ".agents/skills/token-pool-x/a.py", ".agents/skills/lead-ops/SKILL.md",
                  ".agents/skills/seam/SKILL.md", ".agents/rules/git.md", ".agents/rules/sub/a.md", ".agents/README.md",
                  ".claude/skills/x/a.md", ".claude/skills/y/a.md"):
            put(os.path.join(self.top, f))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "x")

    def deny(self, opens, place=".agents/"):
        p = dict(self.p, open=opens)
        head = f"Edit(/{p['worktree']}/{place}"
        return sorted(d[len(head):-1] for d in deny_lib.session_settings(p, self.cfg)["permissions"]["deny"] if d.startswith(head))

    def test_siblings_denied_one_by_one(self):
        got = self.deny([".agents/skills/token-pool"])
        self.assertEqual(got, sorted(["skills/seam/**", "skills/lead-ops/**", "skills/token-pool-x/**", "rules/**", "README.md"]))
        self.assertFalse(any("[" in d for d in got), got)

    def test_default_unchanged(self):
        self.assertIn(f"Edit(/{self.p['worktree']}/.agents/**)", deny_lib.session_settings(self.p, self.cfg)["permissions"]["deny"])

    def test_bad_folders_are_problems(self):
        got = "\n".join(workspace.check_lead(dict(self.p, open=[".agents/skills/none", "svc", ".agents", ".agents/../svc"]), self.cfg))
        self.assertIn("막힌 자리 자체는 열 수 없다: .agents", got)
        self.assertIn("열 폴더에 `..`이 있다: .agents/../svc", got)
        self.assertIn("열 폴더가 없다: .agents/skills/none", got)
        self.assertIn("열 폴더가 막힌 자리 안이 아니다: svc", got)
        self.assertIn(f"Edit(/{self.p['worktree']}/.agents/**)",
                      deny_lib.session_settings(dict(self.p, open=[".agents"]), self.cfg)["permissions"]["deny"])

    def test_several_open_folders(self):
        self.assertEqual(self.deny([".agents/skills/token-pool", ".agents/skills/lead-ops"]),
                         sorted(["skills/seam/**", "skills/token-pool-x/**", "rules/**", "README.md"]))
        self.assertEqual(self.deny([".agents/skills/token-pool", ".agents/rules/sub"]),
                         sorted(["skills/seam/**", "skills/lead-ops/**", "skills/token-pool-x/**", "rules/git.md", "README.md"]))
        self.assertEqual(self.deny([".agents/skills/token-pool", ".agents/skills"]), sorted(["rules/**", "README.md"]))
        self.assertEqual(self.deny([".agents/skills/token-pool", ".agents/skills/token-pool/"]),
                         sorted(["skills/seam/**", "skills/lead-ops/**", "skills/token-pool-x/**", "rules/**", "README.md"]))

    def test_two_covering_places(self):
        opens = [".agents/skills/token-pool", ".claude/skills/x"]
        self.assertEqual(self.deny(opens, ".claude/skills/"), ["y/**"])


if __name__ == "__main__":
    unittest.main()
