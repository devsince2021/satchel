"""libs/settings.py 시험 — 받는 키 목록·모르는 키·꼴, 부르는 쪽(seam·deliver)마다 묶음과 필수 키 요청."""
import json
import os
import tempfile
import unittest

from test import helpers as testing
from libs import settings
from seam.libs import config


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
            "branches.integration", "session.terminal", "seam.pieces", "seam.guide_docs", "seam.lead", "seam.rule_docs", "session.model",
            "deliver.verify", "session.launch", "session.close"]))
        self.assertEqual(config.CUSTOM_ONLY, ("session.launch", "session.close"))
        self.assertEqual([k for k, (_, d) in config.KEYS.items() if d is config.REQUIRED],
                         ["branches.integration", "session.terminal"])


class UnknownAndBadTest(Tmp):
    def test_unknown_keys(self):
        self.assertIn("모르는 키: nope", self.error({**MINIMAL, "nope": 1}))
        self.assertIn("모르는 키: seam.seam", self.error({**MINIMAL, "seam": {"seam": "x"}}))
        self.assertIn("모르는 키: modules", self.error({**MINIMAL, "modules": {"pattern": "x"}}))

    def test_custom_only_keys(self):
        msg = self.error({**MINIMAL, "session": {"terminal": "none", "launch": "x"}})
        self.assertIn("session.launch: session.terminal이 custom일 때만 받는다(지금 'none')", msg)
        self.assertIn("session.close: session.terminal이 custom일 때만", self.error({**MINIMAL, "session": {"terminal": "orca", "close": "x"}}))
        self.assertIn("session.launch: session.terminal이 custom이면 띄울 명령 틀을 적어야 한다",
                      self.error({**MINIMAL, "session": {"terminal": "custom"}}))
        cfg = testing.make({**MINIMAL, "session": {"terminal": "custom", "launch": "tmux new-window {command}", "close": "true"}})
        self.assertEqual((cfg.get("session.launch"), cfg.get("session.close")), ("tmux new-window {command}", "true"))

    def test_wrong_types(self):
        self.assertIn("seam.lead: 글이어야 한다", self.error({**MINIMAL, "seam": {"lead": 1}}))
        self.assertIn("seam.guide_docs: 목록이어야 한다", self.error({**MINIMAL, "seam": {"guide_docs": "AGENTS.md"}}))
        self.assertIn("seam.guide_docs: 글 목록이어야 한다", self.error({**MINIMAL, "seam": {"guide_docs": [1]}}))
        self.assertIn("seam: 사전이어야 한다", self.error({**MINIMAL, "seam": "x"}))
        self.assertIn("session.model: 비어 있으면 안 된다", self.error({**MINIMAL, "session": {"terminal": "none", "model": ""}}))

    def test_bad_json(self):
        self.assertIn("설정을 읽지 못했다", self.error("{"))


class SharedSettingsTest(Tmp):
    """공용 설정 읽기(`libs/settings.py`) — 키 목록은 한 곳, 부르는 쪽은 자기 묶음과 필수 키만 요청한다."""

    def test_seam_keys_are_the_shared_table(self):
        self.assertIs(config.KEYS, settings.KEYS)

    def test_deliver_asks_only_integration(self):
        values, _ = settings.values({"branches": {"integration": "main"}}, ("branches", "deliver"), ("branches.integration",))
        self.assertEqual(values, {"branches.integration": "main", "deliver.verify": ""})
        with self.assertRaises(settings.ConfigError) as e:
            settings.values({}, ("branches", "deliver"), ("branches.integration",))
        self.assertIn("설정에 branches.integration을 적어라", str(e.exception))

    def test_other_groups_are_checked_but_not_returned(self):
        data = {"branches": {"integration": "main"}, "session": {"terminal": "orca"}, "seam": {"lead": "L"}, "deliver": {"verify": "x"}}
        values, written = settings.values(data, ("branches", "deliver"), ("branches.integration",))
        self.assertEqual(sorted(values), ["branches.integration", "deliver.verify"])
        self.assertIn("seam.lead", written)
        with self.assertRaises(settings.ConfigError):
            settings.values({**data, "seam": {"lead": 1}}, ("branches", "deliver"), ())


class PlaceTest(Tmp):
    """설정 파일 자리는 `settings.CONFIG_REL` 하나다."""
    def test_neither_place(self):
        self.assertFalse(settings.present(self.root))
        self.assertEqual(settings.read(self.root), {})


if __name__ == "__main__":
    unittest.main()
