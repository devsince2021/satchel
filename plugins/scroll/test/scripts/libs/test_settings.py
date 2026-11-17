"""libs/settings.py 시험 — 받는 키 목록·모르는 키·걷은 옛 키의 새 자리·꼴, 부르는 쪽(quest·deliver)마다 묶음과 필수 키 요청."""
import json
import os
import tempfile
import unittest

from test import helpers as testing
from libs import settings
from quest.libs import config


MINIMAL = {"branches": {"integration": "main"}, "session": {"terminal": "none"}}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def put(self, text):
        path = config.config_path(self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else json.dumps(text))

    def error(self, data):
        self.put(data)
        with self.assertRaises(config.ConfigError) as cm:
            config.load(self.root)
        return str(cm.exception)


class KeysTest(unittest.TestCase):
    def test_accepted_keys_are_exactly_seven_plus_custom_two(self):
        self.assertEqual(sorted(config.KEYS), sorted([
            "branches.integration", "session.terminal", "quest.quests", "quest.guide_docs", "quest.lead", "quest.rule_docs", "session.model",
            "deliver.verify", "session.launch", "session.close"]))
        self.assertEqual(config.CUSTOM_ONLY, ("session.launch", "session.close"))
        self.assertEqual([k for k, (_, d) in config.KEYS.items() if d is config.REQUIRED],
                         ["branches.integration", "session.terminal"])


class UnknownAndBadTest(Tmp):
    def test_unknown_keys(self):
        self.assertIn("모르는 키: nope", self.error({**MINIMAL, "nope": 1}))
        self.assertIn("모르는 키: quest.quest", self.error({**MINIMAL, "quest": {"quest": "x"}}))
        self.assertIn("모르는 키: modules", self.error({**MINIMAL, "modules": {"pattern": "x"}}))

    def test_removed_keys_say_where_they_went(self):
        """받지 않게 된 옛 키는 모르는 키로 멈추고 무엇으로 바뀌었는지 덧붙인다."""
        cases = [
            ("session", "claude_args", ["--model", "opus"], "session.model로 바뀌었다"),
            ("session", "deny_paths", [], "src/rules/files.json"),
            ("session", "block_git_args", [], "src/rules/git.json"),
            ("tests", "patterns", [], "src/rules/tests.json"),
            ("rules", "patterns", [], "quest.rule_docs.patterns로 옮겼다"),
            ("branches", "work", "x/{folder}", "고정(`quest/{folder}`)"),
            ("branches", "remote_integration", "up/main", "셈한다"),
            ("paths", "quest_list", "x.md", "셈한다"),
            ("quest", "id_prefix", "T", "고정(`Q`)"),
            ("carryover", "sent_addresses", [], "고정(SendMessage)"),
            ("session", "worktree", "{top}/x", "고정"),
            ("session", "record_dir", "x", "고정"),
            ("session", "env", {}, "고정(붙이지 않는다)"),
            ("paths", "quests", "x", "quest.quests로 옮겼다"),
            ("paths", "guide_docs", [], "quest.guide_docs로 옮겼다"),
            ("lead", "name", "x", "quest.lead로 옮겼다"),
            ("merge", "verify", "make", "deliver.verify로 옮겼다"),
        ]
        for group, key, value, word in cases:
            with self.subTest(key=f"{group}.{key}"):
                data = json.loads(json.dumps(MINIMAL))
                data.setdefault(group, {})[key] = value
                msg = self.error(data)
                self.assertIn(f"모르는 키: {group}.{key} — ", msg)
                self.assertIn(word, msg)
        self.assertIn("모르는 키: tests — 프로젝트 설정에서 뺐다 — 플러그인 규칙 src/rules/tests.json",
                      self.error({**MINIMAL, "tests": 1}))

    def test_old_group_alone_says_where(self):
        """0.7.0 묶음(`paths`·`lead`·`merge`)은 묶음째 모르는 키 — 새 자리를 한 줄로."""
        self.assertIn("모르는 키: lead — quest.lead로 옮겼다", self.error({**MINIMAL, "lead": "x"}))
        self.assertIn("모르는 키: merge.verify — deliver.verify로 옮겼다", self.error({**MINIMAL, "merge": {"verify": "x"}}))

    def test_custom_only_keys(self):
        msg = self.error({**MINIMAL, "session": {"terminal": "none", "launch": "x"}})
        self.assertIn("session.launch: session.terminal이 custom일 때만 받는다(지금 'none')", msg)
        self.assertIn("session.close: session.terminal이 custom일 때만", self.error({**MINIMAL, "session": {"terminal": "orca", "close": "x"}}))
        self.assertIn("session.launch: session.terminal이 custom이면 띄울 명령 틀을 적어야 한다",
                      self.error({**MINIMAL, "session": {"terminal": "custom"}}))
        cfg = testing.make({**MINIMAL, "session": {"terminal": "custom", "launch": "tmux new-window {command}", "close": "true"}})
        self.assertEqual((cfg.get("session.launch"), cfg.get("session.close")), ("tmux new-window {command}", "true"))

    def test_wrong_types(self):
        self.assertIn("quest.lead: 글이어야 한다", self.error({**MINIMAL, "quest": {"lead": 1}}))
        self.assertIn("quest.guide_docs: 목록이어야 한다", self.error({**MINIMAL, "quest": {"guide_docs": "AGENTS.md"}}))
        self.assertIn("quest.guide_docs: 글 목록이어야 한다", self.error({**MINIMAL, "quest": {"guide_docs": [1]}}))
        self.assertIn("quest: 사전이어야 한다", self.error({**MINIMAL, "quest": "x"}))
        self.assertIn("session.model: 비어 있으면 안 된다", self.error({**MINIMAL, "session": {"terminal": "none", "model": ""}}))

    def test_bad_json(self):
        self.assertIn("설정을 읽지 못했다", self.error("{"))


class SharedSettingsTest(Tmp):
    """공용 설정 읽기(`libs/settings.py`) — 키 목록은 한 곳, 부르는 쪽은 자기 묶음과 필수 키만 요청한다."""

    def test_quest_keys_are_the_shared_table(self):
        self.assertIs(config.KEYS, settings.KEYS)

    def test_deliver_request_needs_only_integration(self):
        values, _ = settings.values({"branches": {"integration": "main"}}, ("branches", "deliver"), ("branches.integration",))
        self.assertEqual(values, {"branches.integration": "main", "deliver.verify": ""})
        with self.assertRaises(settings.ConfigError) as e:
            settings.values({}, ("branches", "deliver"), ("branches.integration",))
        self.assertIn("설정에 branches.integration을 적어라", str(e.exception))

    def test_other_groups_are_checked_but_not_returned(self):
        data = {"branches": {"integration": "main"}, "session": {"terminal": "orca"}, "quest": {"lead": "L"}, "deliver": {"verify": "x"}}
        values, written = settings.values(data, ("branches", "deliver"), ("branches.integration",))
        self.assertEqual(sorted(values), ["branches.integration", "deliver.verify"])
        self.assertIn("quest.lead", written)
        with self.assertRaises(settings.ConfigError):
            settings.values({**data, "quest": {"lead": 1}}, ("branches", "deliver"), ())


class OldPlaceTest(Tmp):
    """설정 파일이 옛 자리(`settings.OLD_CONFIG_REL`)에만 있으면 새 자리로 옮기라고 한 줄로 알리고 멈춘다."""
    def put_old(self, data):
        path = os.path.join(self.root, settings.OLD_CONFIG_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data))

    def test_only_old_place_says_move(self):
        self.put_old(MINIMAL)
        self.assertTrue(settings.present(self.root))
        with self.assertRaises(config.ConfigError) as cm:
            config.load(self.root)
        self.assertIn("`.satchel/quest.json`으로 옮겨라", str(cm.exception))
        self.assertIn(settings.OLD_CONFIG_REL, str(cm.exception))

    def test_new_place_wins(self):
        self.put_old({"nope": 1})
        self.put(MINIMAL)
        self.assertEqual(config.load(self.root).integration, "main")

    def test_neither_place(self):
        self.assertFalse(settings.present(self.root))
        self.assertEqual(settings.read(self.root), {})


if __name__ == "__main__":
    unittest.main()
