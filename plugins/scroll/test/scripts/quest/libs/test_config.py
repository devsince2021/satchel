"""quest/libs/config.py 시험 — quest가 요청하는 필수 둘·기본값·셈·고정 값·터미널 이름·custom 전용 키·quest.rule_docs·명령 틀 채우기."""
import os
import subprocess
import unittest

from test import helpers as testing
from quest.libs import config
from test.scripts.libs.test_settings import Tmp  # 바탕(픽스처)


MINIMAL = {"branches": {"integration": "main"}, "session": {"terminal": "none"}}


class RequiredTest(Tmp):
    """필수 둘(branches.integration·session.terminal)이 없으면 그것을 적으라는 설정 오류."""

    def test_no_file(self):
        msg = self.error("{}")
        self.assertIn("설정에 branches.integration·session.terminal을 적어라", msg)
        self.assertIn('{"branches": {"integration": "<통합 브랜치>"}}', msg)
        os.remove(config.config_path(self.root))
        with self.assertRaises(config.ConfigError):
            config.load(self.root)
        with self.assertRaises(config.ConfigError):
            config.load(None)

    def test_one_missing(self):
        self.assertIn("설정에 session.terminal을 적어라", self.error({"branches": {"integration": "main"}}))
        self.assertIn("설정에 branches.integration을 적어라", self.error({"session": {"terminal": "none"}}))

    def test_empty_and_unknown_terminal(self):
        self.assertIn("branches.integration: 비어 있으면 안 된다", self.error({**MINIMAL, "branches": {"integration": " "}}))
        msg = self.error({**MINIMAL, "session": {"terminal": "screen"}})
        self.assertIn("session.terminal: 모르는 값 'screen' — none · tmux · orca · custom 가운데 하나", msg)

    def test_terminal_names_follow_rules_file(self):
        """쓸 수 있는 터미널 이름은 규칙 `src/presets/terminals.json`의 프리셋과 custom — 프리셋을 더하면 따라 는다."""
        data = testing.plugin_rules("terminals")
        data["presets"]["screen"] = {"설명": "시험"}
        testing.use_rules(self, "terminals", presets=data["presets"])
        self.put({**MINIMAL, "session": {"terminal": "screen"}})
        self.assertEqual(config.load(self.root).terminal, "screen")


class DefaultsTest(Tmp):
    def test_minimal_gives_defaults(self):
        self.put(MINIMAL)
        cfg = config.load(self.root)
        self.assertEqual(cfg.integration, "main")
        self.assertEqual(cfg.terminal, "none")
        self.assertEqual(cfg.lead, "lead")
        self.assertEqual(cfg.model, "opus")
        self.assertEqual(cfg.get("deliver.verify"), "")
        self.assertEqual(cfg.rel("quests"), ".agents/quests")
        self.assertEqual(cfg.rel("guide_docs"), ["AGENTS.md"])  # CLAUDE.md는 기본값에서 뺐다
        self.assertEqual(cfg.id_shape, "Q-NNN")
        self.assertEqual(cfg.to_lead("Q-001", "시작: ①"), "[Q-001 → lead] 시작: ①")
        self.assertEqual(cfg.from_lead("Q-001"), "[lead → Q-001]")

    def test_defaults_are_not_shared(self):
        self.put(MINIMAL)
        cfg = config.load(self.root)
        cfg.get("quest.guide_docs").append("x")
        self.assertEqual(config.KEYS["quest.guide_docs"][1], ["AGENTS.md"])

    def test_override(self):
        self.put({"branches": {"integration": "trunk"}, "session": {"terminal": "tmux", "model": "sonnet"},
                  "quest": {"lead": "CHIEF", "guide_docs": ["AGENTS.md", "CLAUDE.md"]}, "deliver": {"verify": "make"}})
        cfg = config.load(self.root)
        self.assertEqual((cfg.integration, cfg.terminal, cfg.model, cfg.lead), ("trunk", "tmux", "sonnet", "CHIEF"))
        self.assertEqual(cfg.rel("guide_docs"), ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(cfg.get("deliver.verify"), "make")


class ComputedTest(Tmp):
    """셈 — origin/<integration>, <quests>/README.md·carryover.md, <quests의 부모>/decisions."""

    def test_from_defaults(self):
        self.put(MINIMAL)
        cfg = config.load(self.root)
        self.assertEqual((cfg.remote_integration, cfg.rel("quest_list"), cfg.rel("carryover"), cfg.rel("decisions")),
                         ("origin/main", ".agents/quests/README.md", ".agents/quests/carryover.md", ".agents/decisions"))

    def test_follow_changed_keys(self):
        self.put({"branches": {"integration": "dev/main"}, "quest": {"quests": "svc/work/quests/"}, "session": {"terminal": "none"}})
        cfg = config.load(self.root)
        self.assertEqual(cfg.remote_integration, "origin/dev/main")
        self.assertEqual((cfg.rel("quest_list"), cfg.rel("carryover"), cfg.rel("decisions")),
                         ("svc/work/quests/README.md", "svc/work/quests/carryover.md", "svc/work/decisions"))
        self.assertEqual(testing.make({**MINIMAL, "quest": {"quests": "quests"}}).rel("decisions"), "decisions")

    def test_records_dir_is_git_common_dir(self):
        subprocess.run(["git", "init", "-q", self.root], check=True)
        got = testing.make(MINIMAL, self.root).records_dir()
        self.assertEqual(got, os.path.join(self.root, ".git", "satchel", "quest-sessions"))


class FixedTest(unittest.TestCase):
    """고정 — ID 꼴 Q-NNN·장부 C-NNN·주소 SendMessage, 작업 브랜치 quest/{folder}, 워크트리, 세션 이름, 요구사항 틀."""

    def test_fixed_values(self):
        cfg = testing.make(MINIMAL)
        self.assertTrue(cfg.is_id("Q-012"))
        self.assertFalse(cfg.is_id("Q-12"))
        self.assertEqual(cfg.fmt_id(12), "Q-012")
        self.assertEqual((cfg.carry_prefix, cfg.carry_shape, cfg.sent_addresses), ("C", "C-NNN", ("SendMessage",)))
        self.assertEqual(cfg.work_branch("Q-007-fix-a"), "quest/Q-007-fix-a")
        self.assertEqual(cfg.work_from_branch("quest/Q-007-fix-a"), "Q-007")
        for other in ("main", "quest/X-007-a", "quest/Q-007", "dev/svc-Q-007-a", "quest/Q-0071-a"):
            self.assertIsNone(config.work_from_branch(other), other)
        self.assertEqual(cfg.worktree_for("/w/repo", "Q-007", "Q-007-fix-a"), "/w/repo-q-007")
        self.assertEqual(cfg.title_for("Q-007"), "quest Q-007")
        self.assertEqual(cfg.requirements_template(), os.path.join(testing.PLUGIN, "src", "skills", "quest", "templates", "requirements.md"))
        self.assertEqual(config.PERMISSION_FLAG, "--dangerously-skip-permissions")


class FillTest(unittest.TestCase):
    def test_values_are_quoted(self):
        got = config.fill("tmux new-window -n {title} {command}", {"title": "quest Q-001", "command": "cd /a && claude 'x'"})
        self.assertEqual(got, "tmux new-window -n 'quest Q-001' 'cd /a && claude '\"'\"'x'\"'\"''")

    def test_literal_braces(self):
        self.assertEqual(config.fill("tmux -P -F '#{{pane_id}}' {id}", {"id": "Q-1"}), "tmux -P -F '#{pane_id}' Q-1")

    def test_unknown_placeholder(self):
        with self.assertRaises(config.ConfigError):
            config.fill("x {nope}", {"id": "Q-1"})


class RuleDocsTest(Tmp):
    """"바뀐 규칙 문장" 확인은 설정 `quest.rule_docs`({patterns, optional_prefix, search_dirs}) — 비거나 없으면 꺼짐."""

    def test_default_is_off(self):
        d = testing.make(MINIMAL).rule_docs
        self.assertFalse(d.on)
        self.assertFalse(d.is_rule_doc(".agents/rules/git.md"))
        self.assertEqual((d.optional_prefix, d.search_dirs), ("", []))
        self.assertFalse(testing.make({**MINIMAL, "quest": {"rule_docs": {}}}).rule_docs.on)

    def test_values_come_from_config(self):
        d = testing.make({**MINIMAL, "quest": {"rule_docs": {"patterns": [r"^docs/rules/"], "optional_prefix": "x/"}}}).rule_docs
        self.assertTrue(d.on and d.is_rule_doc("docs/rules/a.md"))
        self.assertFalse(d.is_rule_doc(".agents/rules/git.md"))
        self.assertEqual(d.optional_prefix, "x/")

    def test_bad_values(self):
        def bad(rule_docs, words):
            self.assertIn(words, self.error({**MINIMAL, "quest": {"rule_docs": rule_docs}}))
        bad({"optional_prefix": 1}, "quest.rule_docs.optional_prefix는 글")
        bad({"patterns": ["["]}, "정규식이 아니다")
        bad({"patterns": "x"}, "quest.rule_docs.patterns는 비지 않은 글 목록")
        bad({"nope": []}, "모르는 키: quest.rule_docs.nope")
        bad([], "quest.rule_docs: 사전이어야 한다")


if __name__ == "__main__":
    unittest.main()
