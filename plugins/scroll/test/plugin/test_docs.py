"""플러그인 문서 시험 — 생성 구역이 flow.json과 같음, 스킬·틀·리뷰어·README에 적힌 플러그인 경로와 부명령이 실제로 있음.

보는 문서: 플러그인 뿌리의 README.md·AGENTS.md·CLAUDE.md, `src/` 아래 `.md` 전부(스킬·틀·리뷰어·하위 에이전트 머리말·rules/presets README).
"""
import glob
import os
import re
import unittest

from quest.libs import docgen as rules_doc
from test import helpers as testing

SRC_PATH = re.compile(r"(?:\$\{CLAUDE_PLUGIN_ROOT\}/|<플러그인 뿌리>/|plugins/scroll/)?\b(src/[A-Za-z0-9_./-]*[A-Za-z0-9_/])")
QUEST_CALL = re.compile(r"src/scripts/quest/main\.py\"?\s+([a-z][a-z-]*)")
NOT_PATHS = {"src/test", "src/testFixtures"}  # rules/README의 시험 파일 꼴 예시(프로젝트 쪽 자리) — 플러그인 경로가 아니다
ROOT_DOCS = ("README.md", "AGENTS.md", "CLAUDE.md")  # 플러그인 뿌리의 문서
SKILL_LOCAL = re.compile(r"`((?:templates|reviewers|steps)/[A-Za-z0-9_.-]+\.md)`")


def docs():
    out = [os.path.join(testing.PLUGIN, name) for name in ROOT_DOCS]
    out += sorted(glob.glob(os.path.join(testing.PLUGIN, "src", "**", "*.md"), recursive=True))
    return out


def commands_of_entry():
    """입구 src/scripts/quest/main.py의 COMMANDS — 읽기만(그 파일은 import 길을 바꾸므로 import하지 않는다)."""
    import ast
    tree = ast.parse(read(testing.QUEST))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "COMMANDS")
    return set(ast.literal_eval(node.value))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class GeneratedTest(unittest.TestCase):
    """생성 구역."""

    def test_generated_sections_match_flow_json(self):
        """문서의 생성 구역이 지금 flow.json에서 만든 것과 같다 — 다르면 `rules-doc`을 돌린다."""
        differ = [rel for rel, d in rules_doc.regenerate(write=False) if d]
        self.assertEqual(differ, [], "생성 구역이 flow.json과 다르다 — python3 plugins/scroll/src/scripts/quest/main.py rules-doc")


class StepGuidesTest(unittest.TestCase):
    """단계별 안내 — flow.json의 작업 세션 단계마다 `src/skills/quest/steps/<단계>.md` 하나, 그 밖은 모든 단계 안내 `common.md`뿐.
    SKILL.md는 전체 그림만 — 단계별 안내를 가리키고 단계 절차 절(①~⑥)을 다시 담지 않는다."""

    def setUp(self):
        from quest.libs import rules
        self.steps = rules.flow().hand_steps["작업 세션"]
        self.dir = os.path.join(testing.PLUGIN, "src", "skills", "quest", "steps")

    def test_one_guide_per_work_step(self):
        have = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(self.dir, "*.md")))
        self.assertEqual(have, sorted([*self.steps, "common"]))

    def test_guides_have_sections_and_next(self):
        for name in self.steps:
            with self.subTest(name=name):
                text = read(os.path.join(self.dir, f"{name}.md"))
                for title in ("## 할 일", "## 지킬 것", "## 마치는 조건", "## 커밋", "## 다음"):
                    self.assertIn(title + "\n", text)
                self.assertIn(f"`<ID> {name}:", text)

    def test_skill_points_to_guides_only(self):
        skill = read(os.path.join(testing.PLUGIN, "src", "skills", "quest", "SKILL.md"))
        for name in self.steps:
            self.assertIn(f"steps/{name}.md", skill)
        for old in ("### ① 설계", "### ② 코드 전 검토", "### ③ 구현", "### ④ 코드 뒤 검토", "### ⑤ 리뷰 반영", "### ⑥ 마무리"):
            self.assertNotIn(old, skill)


class PathsInDocsTest(unittest.TestCase):
    """문서에 적힌 플러그인 경로·부명령이 실제로 있다(옮기거나 이름을 바꾸고 문서를 안 고치면 빨강)."""

    def test_src_paths_exist(self):
        missing = []
        for path in docs():
            for m in SRC_PATH.finditer(read(path)):
                rel = m.group(1).rstrip("/.")
                if rel != "src" and rel not in NOT_PATHS and not os.path.exists(os.path.join(testing.PLUGIN, rel)):
                    missing.append(f"{os.path.relpath(path, testing.PLUGIN)}: {rel}")
        self.assertEqual(missing, [])

    def test_quest_subcommands_exist(self):
        commands = commands_of_entry()
        wrong = []
        for path in docs():
            for m in QUEST_CALL.finditer(read(path)):
                if m.group(1) not in commands:
                    wrong.append(f"{os.path.relpath(path, testing.PLUGIN)}: {m.group(1)}")
        self.assertEqual(wrong, [])

    def test_skill_local_files_exist(self):
        """스킬 문서·틀이 가리키는 `templates/…`·`reviewers/…`는 스킬 폴더 안에 있다."""
        skill = os.path.join(testing.PLUGIN, "src", "skills", "quest")
        missing = []
        for path in docs():
            for m in SKILL_LOCAL.finditer(read(path)):
                if not os.path.exists(os.path.join(skill, m.group(1))):
                    missing.append(f"{os.path.relpath(path, testing.PLUGIN)}: {m.group(1)}")
        self.assertEqual(missing, [])

    def test_root_docs_exist(self):
        """뿌리 문서 셋이 있다(없으면 경로 확인이 그 문서를 말없이 건너뛰지 않게)."""
        missing = [name for name in ROOT_DOCS if not os.path.exists(os.path.join(testing.PLUGIN, name))]
        self.assertEqual(missing, [])

    def test_found_something(self):
        """찾는 꼴이 실제로 걸린다(정규식이 아무것도 못 찾아 늘 통과하지 않게)."""
        text = "\n".join(read(p) for p in docs())
        self.assertGreater(len(SRC_PATH.findall(text)), 20)
        self.assertGreater(len(QUEST_CALL.findall(text)), 5)
        self.assertGreater(len(SKILL_LOCAL.findall(text)), 3)


if __name__ == "__main__":
    unittest.main()
