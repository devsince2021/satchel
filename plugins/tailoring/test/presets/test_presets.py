"""프리셋 파일 시험 — src/presets/terminals.json 읽기(seam/libs/presets): 정본 값, 깨진 꼴, 명령 틀 채우기."""
import unittest


from test import helpers as testing
from seam.libs import presets
from test.rules.test_rules import Files, shipped  # 바탕(픽스처)


class ShippedPresetsTest(Files):
    """정본 프리셋."""

    def test_terminals(self):
        t = shipped("terminals", presets.Terminals)
        self.assertEqual(t.names, ("none", "tmux", "orca", "custom"))
        self.assertIsNone(t.presets["none"]["launch"])
        self.assertEqual(t.presets["orca"]["bin"]["fallbacks"], ["/Applications/Orca.app/Contents/Resources/bin/orca"])
        self.assertEqual(list(t.presets["orca"]["env"]), ["ORCA_WORKTREE_ID"])
        self.assertEqual(list(t.presets["tmux"]["env"]), ["TMUX"])


class BrokenPresetsTest(Files):
    """깨진 프리셋 꼴과 명령 틀."""

    def test_terminals(self):
        data = testing.plugin_rules("terminals")
        ps = data["presets"]

        def with_preset(name, p):
            return {"presets": {**ps, name: p}}
        self.bad(presets.Terminals, {"presets": {}}, "presets는 비지 않은 사전")
        self.bad(presets.Terminals, with_preset("custom", {}), "`custom`은")
        self.bad(presets.Terminals, with_preset("Bad", {}), "프리셋 이름 'Bad'")
        self.bad(presets.Terminals, with_preset("x", {"close": []}), "launch가 없는 프리셋")
        tmux = ps["tmux"]
        self.bad(presets.Terminals, with_preset("x", {**tmux, "launch": ["{bin}", "{nope}"]}), "모르는 자리표 {nope}")
        self.bad(presets.Terminals, with_preset("x", {**tmux, "launch": ["{bin}", "{env:HOME}"]}), "env에 적지 않은 환경 변수")
        self.bad(presets.Terminals, with_preset("x", {**tmux, "close": [["{bin}", "{command}"]]}), "모르는 자리표 {command}")
        self.bad(presets.Terminals, with_preset("x", {**tmux, "handle": [{"guess": "x"}]}), "handle[0]")
        self.bad(presets.Terminals, with_preset("x", {**tmux, "handle": [{"regex": "("}]}), "정규식이 아니다")
        orca = ps["orca"]
        self.bad(presets.Terminals, with_preset("x", {**orca, "find": {**orca["find"], "tries": 0}}), "find.tries는 1~10")
        self.bad(presets.Terminals, with_preset("x", {k: v for k, v in tmux.items() if k != "bin"}), "`bin`이 없다")

    def test_fill_argv(self):
        self.assertEqual(presets.fill_argv(["{bin}", "-F", "#{{window_id}}", "id:{env:W}"], {"bin": "/b"}, {"W": "w1"}),
                         ["/b", "-F", "#{window_id}", "id:w1"])
        self.assertEqual(presets.fill_argv(["{command}"], {"command": "cd '/a b' && claude"}), ["cd '/a b' && claude"])
        with self.assertRaises(KeyError):
            presets.fill_argv(["{env:NOPE_X}"], {}, {})


if __name__ == "__main__":
    unittest.main()
