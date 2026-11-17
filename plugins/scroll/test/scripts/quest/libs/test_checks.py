"""quest/libs/checks/ 시험 — 끝 확인 항목(기록 파일 넷과 절, 요구사항 틀, 리뷰 반영표, 할 일 꼴·시험 커밋 차례, 넘길 일, 바뀐 규칙 문장 켬·끔)."""
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout

from test import helpers as testing
from quest.commands import end as end_cmd
from quest.libs import checks, commits, config
from quest.libs import rules as plugin_rules
from quest.libs.checks import carry, records, requirements, rules
from quest.libs.context import Context
from quest.libs.text import read


TABLE = "| # | 지적 | 출처 | 등급 | 한 일 | 시험 |\n| --- | --- | --- | --- | --- | --- |\n"


RETRO = ("# 회고\n\n## 끝 검증\n\n- python3 -m unittest → OK\n\n## 어긋난 것\n\n- 없음\n\n"
         "## 바뀐 규칙 문장\n\n- 없음\n\n## 닫을 장부 줄\n\n- 없음\n\n## 넘길 일\n\n- 없음\n")


README = "# workflow\n\n## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n"


LEDGER = "| ID | 출처 | 받는 쪽 | 내용 | 상태 | 근거 |\n| --- | --- | --- | --- | --- | --- |\n"


def at(hour):
    return f"2026-11-01T{hour:02d}:00:00+00:00"


V2 = "Q-061"


V2_QUEST = "quests/Q-061-sample"


V2_REQ = ("# t\n\n- 작업: Q-061 · 결정 번호: 0611~0620 · 브랜치: quest/Q-061-sample · 흐름: quest\n"
          "- 날짜: 2026-11-12 · 요청: 사용자 · 대상: guard\n- 출발: 시험\n\n"
          "## 문제\n\n- 어긋남\n\n## 요구\n\n- R1. 하나\n\n## 범위\n\n- 안: x\n\n## 수용 기준\n\n- 시험 OK\n")


V2_PLAN = ("# 계획\n\n## 잰 코드 사실\n\n- `rg x` → 3\n\n## 결정\n\n- 없음\n\n## 할 일\n\n"
           "- [x] 1. 하나 — 시험 `test_a`\n- [x] 2. 둘 — 시험 `test_b`\n- [x] 3. 문서 — TDD 예외 — 문서만\n\n"
           "## 코드 전 검토\n\n- Minor 1 — 둠\n\n## 구현하며 바뀐 것\n\n- 없음\n")


V2_RETRO = RETRO.replace("## 넘길 일\n\n- 없음\n", "## 넘길 일\n\n- gateway: 대조 대상 옮기기\n")


V2_REVIEW = ("# 리뷰\n\n## 동작\n\n- I1 경계\n\n## 문서·규칙\n\n- 없음\n\n## 반영\n\n" + TABLE
             + "| 1 | 경계 | 동작 | Important | 고침 abc1234 | test_edge |\n| 2 | 말 | 문서·규칙 | Minor | 고침 — 낱말 맞춤 | — |\n")


TEST_JAVA = "libs/x/src/test/java/ATest.java"


MAIN_JAVA = "libs/x/src/main/java/A.java"


# 시험 저장소 본 — 같은 저장소를 매번 git으로 다시 쌓지 않고 복사한다(판정은 복사본에 그대로 돈다).
# 첫 상태(setUp 끝)는 한 번만 만들고, 첫 상태에서 같은 인자로 부른 v2_finish의 결과도 한 번만 만든다.
_CACHE = {"dir": None, "base": None, "finished": {}}


def _cache_dir():
    if _CACHE["dir"] is None:
        _CACHE["dir"] = os.path.realpath(tempfile.mkdtemp())
    return _CACHE["dir"]


class Base(unittest.TestCase):
    """작업 Q-061. 옛 번호 Q-001~Q-060은 README `버림` 줄만 둔다(옛 요구사항 파일은 없다)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.module = os.path.join(self.tmp, "svc")
        self.wf = os.path.join(self.module, ".agents", "workflow")
        if _CACHE["base"] is None:
            self.build()
            _CACHE["base"] = os.path.join(_cache_dir(), "base")
            shutil.copytree(self.tmp, _CACHE["base"], symlinks=True)
        else:
            self.restore(_CACHE["base"])
        self.ctx = Context(self.tmp)
        self.pristine = True  # 첫 상태 그대로인가 — git·put·commit·touch를 부르면 거짓

    def restore(self, snapshot):
        shutil.rmtree(self.tmp)
        shutil.copytree(snapshot, self.tmp, symlinks=True)

    def build(self):
        """첫 상태: Q-061 요구사항 커밋, `dev/main` 가지."""
        for d in ("decisions", V2_QUEST):
            os.makedirs(os.path.join(self.wf, d))
        self.git("init", "-q")
        testing.write(self.tmp)
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")
        # 커밋 뒤 git이 뒤에서 도는 gc가 저장소 본을 복사하는 동안 객체를 옮기지 않게
        self.git("config", "gc.auto", "0")
        self.git("config", "maintenance.auto", "false")
        rows = "".join(f"| Q-{i:03d} | old | 버림 | — |\n" for i in range(1, 61))
        self.put("quests/README.md", README + rows + "| Q-061 | t | 진행 | 0611~0620 |\n")
        self.put("quests/carryover.md", LEDGER)
        self.put(f"{V2_QUEST}/requirements.md", V2_REQ)
        self.commit("Q-061 req: 요구사항", at(0))
        self.git("branch", "dev/main")  # 작업 범위 merge-base

    def git(self, *args):
        self.pristine = False
        return subprocess.run(["git", "-C", self.tmp, *args], capture_output=True, text=True, check=True).stdout

    def put(self, rel, text):
        self.pristine = False
        path = os.path.join(self.wf, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, title, when):
        self.pristine = False
        env = dict(os.environ, GIT_AUTHOR_DATE=when)
        self.git("add", "-A")
        subprocess.run(["git", "-C", self.tmp, "commit", "-q", "--allow-empty", "-m", title], env=env, check=True)

    def touch(self, rel):
        self.pristine = False
        path = os.path.join(self.module, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("x\n")

    def v2_finish(self, todo_commits=None, plan=V2_PLAN, retro=V2_RETRO, later_plan=None, plan_touch=None, review=V2_REVIEW):
        """plan → plan-review → 할 일 커밋들 → review → done. todo_commits: [(제목 꼬리, 건드릴 파일 — None이면 빈 커밋)].
        첫 상태에서 부르면 같은 인자의 결과 저장소를 한 번만 쌓고 다음부터는 복사한다."""
        key = repr((todo_commits, plan, retro, later_plan, plan_touch, review)) if getattr(self, "pristine", False) else None
        if key in _CACHE["finished"]:
            self.restore(_CACHE["finished"][key])
            self.pristine = False
            return
        self._v2_finish(todo_commits, plan, retro, later_plan, plan_touch, review)
        if key is not None:
            snapshot = tempfile.mkdtemp(dir=_cache_dir())
            os.rmdir(snapshot)
            try:
                shutil.copytree(self.tmp, snapshot, symlinks=True)
            except (OSError, shutil.Error):
                shutil.rmtree(snapshot, True)  # 본을 못 만들면 다음에 다시 쌓는다
            else:
                _CACHE["finished"][key] = snapshot

    def _v2_finish(self, todo_commits, plan, retro, later_plan, plan_touch, review):
        if todo_commits is None:
            todo_commits = [("test: #1 a", TEST_JAVA), ("run: #1 a", MAIN_JAVA),
                            ("test: #2 b", "libs/x/src/testFixtures/java/F.java"), ("run: #2 b", MAIN_JAVA),
                            ("run: #3 문서", "README.md")]
        self.put(f"{V2_QUEST}/plan.md", plan)
        if plan_touch:
            self.touch(plan_touch)
        self.commit("Q-061 plan: x", at(1))
        self.commit("Q-061 plan-review: x", at(2))
        for tail, rel in todo_commits:
            if rel:
                self.touch(rel)
            self.commit(f"Q-061 {tail}", at(3))
        self.put(f"{V2_QUEST}/review.md", review)
        self.commit("Q-061 review: x", at(4))
        self.put(f"{V2_QUEST}/retro.md", retro)
        if later_plan is not None:  # 코드 전 검토 뒤에 고친 계획
            self.put(f"{V2_QUEST}/plan.md", later_plan)
        self.commit("Q-061 done: x", at(5))

    def end(self):
        return checks.end_problems(self.ctx, V2)


V2Base = Base


def tearDownModule():
    if _CACHE["dir"]:
        shutil.rmtree(_CACHE["dir"], True)
    _CACHE.update(dir=None, base=None, finished={})


class TddOrderTest(Base):
    """할 일마다 시험 커밋(`Q-NNN test: #N`)이 구현 커밋(`Q-NNN run: #N`)보다 앞, 시험 커밋은 시험 파일만."""

    def test_clean_passes(self):
        self.v2_finish()
        self.assertEqual(self.end(), [])

    def test_test_step_is_counted(self):
        self.v2_finish()
        self.assertIn("test", [s for s, _ in commits.steps_of(self.ctx, V2)])

    def test_run_before_test_blocks(self):
        self.v2_finish([("run: #1 a", MAIN_JAVA), ("test: #1 a", TEST_JAVA),
                        ("test: #2 b", TEST_JAVA), ("run: #2 b", MAIN_JAVA)])
        self.assertIn("할 일 1: 구현 커밋이 시험 커밋보다 앞이다(TDD — 시험 `Q-061 test: #1` 먼저)", self.end())

    def test_missing_test_commit_blocks(self):
        self.v2_finish([("run: #1 a", MAIN_JAVA), ("test: #2 b", TEST_JAVA), ("run: #2 b", MAIN_JAVA)])
        self.assertIn("할 일 1: 시험 커밋 `Q-061 test: #1 …`이 없다(TDD가 맞지 않으면 할 일 줄에 `TDD 예외 — <까닭>`)", self.end())

    def test_missing_run_commit_blocks(self):
        self.v2_finish([("test: #1 a", TEST_JAVA), ("test: #2 b", TEST_JAVA), ("run: #2 b", MAIN_JAVA)])
        self.assertIn("할 일 1: 구현 커밋 `Q-061 run: #1 …`이 없다", self.end())

    def test_test_commit_touching_main_blocks(self):
        self.v2_finish([("test: #1 a", MAIN_JAVA), ("run: #1 a", MAIN_JAVA),
                        ("test: #2 b", TEST_JAVA), ("run: #2 b", MAIN_JAVA)])
        self.assertTrue(any(x.startswith("시험 커밋 ") and "시험 파일이 아닌 것을 건드린다: svc/libs/x/src/main/java/A.java" in x
                            for x in self.end()))

    def test_several_todos_in_one_commit(self):
        self.v2_finish([("test: #1 #2 ab", TEST_JAVA), ("run: #1 #2 ab", MAIN_JAVA)])
        self.assertEqual(self.end(), [])

    def test_hash_number_is_whole(self):
        """`#12`는 할 일 1이 아니다."""
        self.v2_finish([("test: #12 x", TEST_JAVA), ("run: #1 a", MAIN_JAVA),
                        ("test: #2 b", TEST_JAVA), ("run: #2 b", MAIN_JAVA)])
        self.assertTrue(any(x.startswith("할 일 1: 시험 커밋") for x in self.end()))

    def test_open_todo_blocks(self):
        self.v2_finish(plan=V2_PLAN.replace("- [x] 2.", "- [ ] 2."))
        self.assertIn("할 일 2가 끝나지 않았다(`- [ ]`)", self.end())

    def test_exception_needs_reason(self):
        self.v2_finish(plan=V2_PLAN.replace("TDD 예외 — 문서만", "TDD 예외"))
        self.assertTrue(any(x.startswith("할 일 3: 시험 커밋") for x in self.end()))

    def test_unparsed_todo_line_blocks(self):
        """할 일 줄이 꼴에서 벗어나면 검사가 말없이 꺼지지 않고 막는다."""
        self.v2_finish(plan=V2_PLAN.replace("- [x] 1.", "- [X] 1.").replace("- [x] 2.", "- [x] 2)"))
        p = self.end()
        self.assertIn("plan.md 할 일 줄 꼴이 아니다(`- [ ] N. …`·`- [x] N. …`): - [X] 1. 하나 — 시험 `test_a`", p)
        self.assertIn("plan.md 할 일 줄 꼴이 아니다(`- [ ] N. …`·`- [x] N. …`): - [x] 2) 둘 — 시험 `test_b`", p)

    def test_no_todo_blocks(self):
        self.v2_finish(plan=V2_PLAN.replace("- [x] 1. 하나 — 시험 `test_a`\n- [x] 2. 둘 — 시험 `test_b`\n- [x] 3. 문서 — TDD 예외 — 문서만\n",
                                            "할 일은 위 결정대로\n"))
        self.assertIn("plan.md `## 할 일`에 `- [x] N. …` 할 일이 없다", self.end())

    def test_empty_test_commit_blocks(self):
        self.v2_finish([("test: #1 a", None), ("run: #1 a", MAIN_JAVA), ("test: #2 b", TEST_JAVA), ("run: #2 b", MAIN_JAVA)])
        self.assertTrue(any(x.startswith("시험 커밋 ") and "시험 파일을 바꾸지 않는다" in x for x in self.end()))

    def test_unnumbered_run_commit_blocks(self):
        self.v2_finish([("run: 먼저 구현", MAIN_JAVA), ("test: #1 #2 ab", TEST_JAVA), ("run: #1 #2 ab", None)])
        self.assertTrue(any(x.startswith("구현 커밋 ") and "할 일 번호 `#N`이 없다" in x for x in self.end()))

    def test_code_in_plan_commit_before_test_blocks(self):
        self.v2_finish(plan_touch=MAIN_JAVA)
        self.assertTrue(any("시험 커밋보다 앞선 plan 커밋" in x and "svc/libs/x/src/main/java/A.java" in x for x in self.end()))

    def test_docs_in_plan_commit_pass(self):
        self.v2_finish(plan_touch="libs/x/NOTE.md")
        self.assertEqual(self.end(), [])

    def test_exception_added_after_plan_review_blocks(self):
        """코드 전 검토 뒤에 붙인 `TDD 예외`는 `## 구현하며 바뀐 것`에 그 할 일과 까닭이 있어야 한다."""
        later = V2_PLAN.replace("- [x] 2. 둘 — 시험 `test_b`", "- [x] 2. 둘 — TDD 예외 — 설정만")
        self.v2_finish([("test: #1 a", TEST_JAVA), ("run: #1 a", MAIN_JAVA), ("run: #2 b", MAIN_JAVA)], later_plan=later)
        self.assertIn("할 일 2: `TDD 예외`가 코드 전 검토(plan-review) 뒤에 생겼다 — `## 구현하며 바뀐 것`에 `할 일 2`와 까닭을 적는다",
                      self.end())

    def test_exception_added_after_plan_review_with_reason_passes(self):
        later = (V2_PLAN.replace("- [x] 2. 둘 — 시험 `test_b`", "- [x] 2. 둘 — TDD 예외 — 설정만")
                 .replace("## 구현하며 바뀐 것\n\n- 없음\n", "## 구현하며 바뀐 것\n\n- 할 일 2를 TDD 예외로 — 설정 값만 바뀜\n"))
        self.v2_finish([("test: #1 a", TEST_JAVA), ("run: #1 a", MAIN_JAVA), ("run: #2 b", MAIN_JAVA)], later_plan=later)
        self.assertEqual(self.end(), [])

    def test_test_file_kinds(self):
        """시험 파일은 규칙 사본(SVC_RULES)의 꼴 — `src/test/`·`src/testFixtures/` 아래, `test_*.py`."""
        for path in ("svc/libs/x/src/test/java/A.java", "svc/libs/x/src/testFixtures/java/F.java",
                     "svc/libs/x/src/test/resources/db/seed.sql", "svc/.agents/workflow/guard/test_x.py"):
            self.assertTrue(plugin_rules.tests().is_test_file(path), path)
        for path in ("svc/libs/x/src/main/java/A.java", "svc/.agents/workflow/guard/x.py",
                     "svc/.agents/workflow/quests/Q-061-x/plan.md", "svc/src/contest/A.java", "svc/build.kts",
                     "svc/bootstrap/src/integrationTest/java/I.java", "svc/libs/x/src/main/java/test_x.py.bak",
                     "web/apps/host/src/x.ts", "web/test.ts", "web/apps/host/src/test-helpers.ts"):
            self.assertFalse(plugin_rules.tests().is_test_file(path), path)


class V2RecordsTest(V2Base):
    """작업 세션은 README 줄을 고치지 않고, 넘길 일은 번호 없이 `- <받는 쪽>: <내용>`."""

    def test_readme_in_progress_passes(self):
        self.v2_finish()
        self.assertEqual(self.end(), [])

    def test_readme_row_still_needed(self):
        self.v2_finish()
        text = read(os.path.join(self.wf, "quests", "README.md"))
        self.put("quests/README.md", text.replace("| Q-061 | t | 진행 | 0611~0620 |\n", ""))
        self.assertIn("작업 목록(svc/.agents/workflow/quests/README.md)에 Q-061 줄이 없다", self.end())

    def test_carry_item_needs_receiver(self):
        self.v2_finish(retro=RETRO.replace("## 넘길 일\n\n- 없음\n", "## 넘길 일\n\n- 대조 대상 옮기기\n"))
        self.assertIn("retro.md 넘길 일 꼴이 아니다(`- <받는 쪽>: <내용>` 또는 `- 없음`): 대조 대상 옮기기", self.end())

    def test_carry_item_with_number_blocks(self):
        """번호는 리드가 합칠 때 매긴다 — README가 아직 `끝`이 아닌데 작업 세션이 단 `[C-NNN]`은 막는다."""
        self.v2_finish(retro=RETRO.replace("## 넘길 일\n\n- 없음\n", "## 넘길 일\n\n- gateway: 옮기기 [C-001]\n"))
        self.assertTrue(any("넘길 일 번호는 리드가 합칠 때 매긴다" in x for x in self.end()))

    def test_carry_sub_items_blocked(self):
        """들여 쓴 하위 항목은 번호를 어디에 매길지 모호하다 — 한 항목 한 줄."""
        self.v2_finish(retro=RETRO.replace("## 넘길 일\n\n- 없음\n", "## 넘길 일\n\n- gateway: 옮기기\n  - 하나 더\n"))
        self.assertIn("retro.md 넘길 일에 들여 쓴 하위 항목을 두지 않는다(한 항목 한 줄): 하나 더", self.end())

    def test_carry_star_item_blocks(self):
        """번호는 `- ` 항목에만 매긴다(quest merge) — `* `·`1. ` 항목은 그 꼴이 아니다."""
        self.v2_finish(retro=RETRO.replace("## 넘길 일\n\n- 없음\n", "## 넘길 일\n\n* gateway: 옮기기\n1. lead: 끝 검사\n"))
        p = self.end()
        self.assertIn("retro.md 넘길 일은 `- ` 항목만 쓴다: gateway: 옮기기", p)
        self.assertIn("retro.md 넘길 일은 `- ` 항목만 쓴다: lead: 끝 검사", p)

    def test_receiver_shape(self):
        for item, ok in (("gateway: x", True), ("총괄·DevOps: x", True), ("lead: 끝 검사에서 `a:b` 돌림", True),
                         ("`x`: y", False), ("아주 긴 받는 쪽 이름이 스무 자를 넘는 경우: y", False), (": y", False)):
            self.assertEqual(carry.CARRY_ITEM.match(item) is not None, ok, item)


class ReviewOutcomeTest(V2Base):
    """반영 표의 모든 지적은 `고침`·`기각`(까닭)·`넘김`(C 번호·넘길 일) 가운데 하나."""

    def row(self, grade, done, test="—"):
        return V2_REVIEW.replace("| 2 | 말 | 문서·규칙 | Minor | 고침 — 낱말 맞춤 | — |", f"| 2 | 말 | 문서·규칙 | {grade} | {done} | {test} |")

    def problems(self, grade, done, test="—", retro=V2_RETRO):
        self.v2_finish(review=self.row(grade, done, test), retro=retro)
        return [x for x in self.end() if x.startswith("review.md 반영 2")]

    def test_three_outcomes_pass(self):
        for grade, done in (("Minor", "고침 — 낱말"), ("Minor", "기각 — 코드에 이미 있음"), ("Important", "넘김 [C-001] 범위 밖")):
            with self.subTest(done=done):
                self.setUp()
                self.assertEqual(self.problems(grade, done), [])

    def test_hand_off_by_retro_item_passes(self):
        self.assertEqual(self.problems("Minor", "넘김 — 넘길 일(gateway)"), [])

    def test_old_values_blocked(self):
        for done in ("반영 abc", "둠 — 뜻 같음", "기록만", "—"):
            with self.subTest(done=done):
                self.setUp()
                self.assertIn(f"review.md 반영 2: 한 일 '{done}'은 `고침`·`기각`·`넘김` 가운데 하나로 시작해야 한다",
                              self.problems("Minor", done))

    def test_reject_needs_reason(self):
        self.assertIn("review.md 반영 2: `기각`인데 까닭이 없다(`기각 — <까닭>`)", self.problems("Minor", "기각"))

    def test_hand_off_needs_target(self):
        retro = RETRO  # 넘길 일 `- 없음`
        self.assertIn("review.md 반영 2: `넘김`인데 C 번호도 retro `## 넘길 일` 항목도 없다", self.problems("Minor", "넘김 — 나중에", retro=retro))

    def test_reject_is_not_a_grade(self):
        self.assertTrue(any("등급 '기각'" in x for x in self.problems("기각", "기각 — 틀림")))

    def test_fixed_critical_still_needs_test(self):
        self.assertTrue(any("'시험' 칸이 비었다" in x for x in self.problems("Critical", "고침 abc")))


class RequirementsTemplateTest(V2Base):
    """요구사항이 틀(`templates/requirements.md`)의 머리 칸·절에 맞는지."""

    def test_good_passes(self):
        self.assertEqual(requirements.requirements_problems(V2_REQ, self.ctx.requirements_template()), [])

    def test_missing_head_field(self):
        p = requirements.requirements_problems(V2_REQ.replace("- 출발: 시험\n", ""), self.ctx.requirements_template())
        self.assertIn("요구사항 머리에 틀의 칸 '출발:'이 없다", p)

    def test_missing_or_empty_section(self):
        p = requirements.requirements_problems(V2_REQ.replace("## 범위\n\n- 안: x\n\n", "").replace("- R1. 하나\n", "- R1. <확인할 수 있는 문장>\n"), self.ctx.requirements_template())
        self.assertIn("요구사항 `## 범위`이 비었다", p)
        self.assertIn("요구사항 `## 요구`이 비었다", p)

    def test_template_fields_are_read_from_template(self):
        fields, sections = requirements.template_fields(self.ctx.requirements_template())
        self.assertEqual(fields, ["작업", "결정 번호", "브랜치", "흐름", "날짜", "요청", "대상", "출발"])
        self.assertEqual(sections, ["## 문제", "## 요구", "## 범위", "## 수용 기준"])

    def test_end_uses_template_check(self):
        self.put(f"{V2_QUEST}/requirements.md", V2_REQ.replace("- 출발: 시험\n", ""))
        self.v2_finish()
        self.assertIn("요구사항 머리에 틀의 칸 '출발:'이 없다", self.end())


class RuleChangeTest(Base):
    """작업 범위(merge-base..HEAD)에서 규칙 문서를 바꿨으면 retro `## 바뀐 규칙 문장`에 파일마다 옛 → 새 줄."""

    LINE = "- svc/.agents/rules/deps.md:deps-01 · 옛 문장 → 새 문장 · 결정 0611\n"

    def retro(self, lines):
        return V2_RETRO.replace("## 바뀐 규칙 문장\n\n- 없음\n", "## 바뀐 규칙 문장\n\n" + lines)

    def change(self, *rels):
        for rel in rels:
            self.touch(rel)
        self.commit("Q-061 fix: 규칙 문장", at(6))

    def rule_problems(self):
        return [x for x in self.end() if "규칙 문장" in x or "규칙 문서" in x]

    def test_rule_doc_changed_with_none_blocks(self):
        self.v2_finish()
        self.change(".agents/rules/deps.md")
        p = self.rule_problems()
        self.assertTrue(any("`## 바뀐 규칙 문장`" in x and "svc/.agents/rules/deps.md" in x for x in p), p)

    def test_rule_doc_changed_with_line_passes(self):
        self.v2_finish(retro=self.retro(self.LINE))
        self.change(".agents/rules/deps.md")
        self.assertEqual(self.end(), [])

    def test_path_without_svc_prefix_passes(self):
        self.v2_finish(retro=self.retro(self.LINE.replace("svc/.agents", ".agents")))
        self.change(".agents/rules/deps.md")
        self.assertEqual(self.end(), [])

    def test_unlisted_rule_file_blocks(self):
        self.v2_finish(retro=self.retro(self.LINE))
        self.change(".agents/rules/deps.md", ".agents/rules/contracts.md")
        p = self.rule_problems()
        self.assertTrue(any("svc/.agents/rules/contracts.md" in x for x in p), p)
        self.assertFalse(any("svc/.agents/rules/deps.md" in x for x in p), p)

    def test_line_without_arrow_blocks(self):
        self.v2_finish(retro=self.retro("- svc/.agents/rules/deps.md:deps-01 고침\n"))
        self.change(".agents/rules/deps.md")
        self.assertTrue(any("옛 문장 → 새 문장" in x for x in self.rule_problems()))

    def test_nested_and_bootstrap_rules_count(self):
        for rel in (".agents/rules/sub/a.md", "bootstrap/.agents/rules/specs.lock", "platform-services/gateway/.agents/rules/x.md"):
            with self.subTest(rel=rel):
                self.setUp()
                self.v2_finish()
                self.change(rel)
                self.assertTrue(any("svc/" + rel in x for x in self.rule_problems()), rel)

    def test_non_rule_docs_do_not_count(self):
        self.v2_finish()
        self.change(".agents/organization/sessions.md", ".agents/rules-old.md", "src/main/resources/rules/a.md")
        self.assertEqual(self.end(), [])

    def test_changes_before_merge_base_do_not_count(self):
        self.touch(".agents/rules/deps.md")
        self.commit("lead: 규칙", at(0))
        self.git("branch", "-f", "dev/main", "HEAD")
        self.v2_finish()
        self.assertEqual(self.end(), [])

    def test_lines_without_rule_doc_change_warn_only(self):
        self.v2_finish(retro=self.retro("- svc/.agents/organization/sessions.md:1 · 옛 → 새 · 결정 0611\n"))
        self.assertEqual(self.end(), [])
        self.assertTrue(any("규칙 문서" in x for x in checks.end_warnings(self.ctx, V2)))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(end_cmd.main([V2], self.ctx), 0)
        self.assertIn("- 경고: ", out.getvalue())
        self.assertIn("quest_check: 통과", out.getvalue())

    def test_no_warning_when_none(self):
        self.v2_finish()
        self.assertEqual(checks.end_warnings(self.ctx, V2), [])

    def test_missing_section_blocks(self):
        self.v2_finish(retro=V2_RETRO.replace("## 바뀐 규칙 문장\n\n- 없음\n\n", ""))
        self.assertIn("retro.md `## 바뀐 규칙 문장`이 비었다", self.end())

    def test_no_tech_main_blocks(self):
        self.v2_finish()
        self.git("branch", "-D", "dev/main")
        self.assertTrue(any("dev/main" in x for x in self.end()))

    def test_is_rule_doc(self):
        for path, ok in (("svc/.agents/rules/deps.md", True), (".agents/rules/git.md", True),
                         ("svc/bootstrap/.agents/rules/x.lock", True), ("svc/.agents/rules/README", False),
                         ("svc/.agents/workflow/README.md", False), ("svc/x.agents/rules/a.md", False)):
            self.assertEqual(testing.make().rule_docs.is_rule_doc(path), ok, path)
    def test_placeholder_inside_code_span_passes(self):
        self.v2_finish(retro=self.retro("- svc/.agents/rules/deps.md:deps-01 · `<대상>은 하나` → `<대상>은 둘` · 결정 0611\n"))
        self.change(".agents/rules/deps.md")
        self.assertEqual(self.end(), [])

    def test_unparsed_block_message_shows_shape(self):
        self.v2_finish()
        self.change(".agents/rules/deps.md")
        self.assertTrue(any("<규칙 파일>:<규칙 ID 또는 절>" in x for x in self.rule_problems()))

    def test_template_retro_has_all_sections(self):
        skill = os.path.join(config.PLUGIN_ROOT, "src", "skills", "quest", "templates")
        text = read(os.path.join(skill, "retro.md"))
        for title in records.SECTIONS["retro.md"]:
            self.assertIn(title + "\n", text)
        # 기본 틀에는 그 절이 없다(주석으로 꼴만) — 켠 설정에서만 끝 확인이 그 절을 요구한다
        self.assertNotIn(records.RULE_SECTION + "\n", text)
        self.assertNotIn(records.RULE_SECTION, records.SECTIONS["retro.md"])
        self.assertEqual(records.sections(self.ctx.cfg)["retro.md"],
                         ("## 끝 검증", "## 어긋난 것", records.RULE_SECTION, "## 닫을 장부 줄", "## 넘길 일"))

    def test_same_name_other_place_blocks(self):
        """줄의 파일 자리는 바뀐 경로와 같아야 한다 — 다른 자리 같은 이름 파일 줄로는 안 된다."""
        self.v2_finish(retro=self.retro("- svc/platform-services/gateway/.agents/rules/deps.md:x · `a` → `b` · 결정 0711\n"))
        self.change(".agents/rules/deps.md")
        self.assertTrue(any("svc/.agents/rules/deps.md" in x for x in self.rule_problems()))

    def test_path_only_in_reason_blocks(self):
        self.v2_finish(retro=self.retro("- svc/.agents/rules/other.md:x · `a` → `b` · svc/.agents/rules/deps.md 참고\n"))
        self.change(".agents/rules/deps.md")
        self.assertTrue(any("빠졌다" in x and "svc/.agents/rules/deps.md" in x for x in self.rule_problems()))

    def test_non_ascii_rule_doc_counts(self):
        self.v2_finish()
        self.change(".agents/rules/규칙.md")
        self.assertTrue(any("svc/.agents/rules/규칙.md" in x for x in self.rule_problems()))

    def test_non_ascii_rule_doc_listed_passes(self):
        self.v2_finish(retro=self.retro("- svc/.agents/rules/규칙.md:be-규칙-01 · `a` → `b` · 결정 0711\n"))
        self.change(".agents/rules/규칙.md")
        self.assertEqual(self.end(), [])

    def test_rule_change_on_tech_main_after_branch_does_not_count(self):
        """분기 뒤 `dev/main`에만 생긴 규칙 문서 변경은 작업 범위가 아니다(merge-base, 리베이스 전 ⑥)."""
        self.v2_finish()
        here = self.git("branch", "--show-current").strip()
        self.git("checkout", "-q", "dev/main")
        self.touch(".agents/rules/deps.md")
        self.commit("lead: 규칙", at(7))
        self.git("checkout", "-q", here)
        self.assertEqual(self.end(), [])

    def test_double_space_none_is_none(self):
        self.v2_finish(retro=self.retro("-  없음\n"))
        self.assertEqual(self.end(), [])
        self.assertEqual(rules.rule_items(self.retro("-  없음\n")), [])


class RulesOffTest(Base):
    """설정 `quest.rule_docs`가 없으면(기본값) "바뀐 규칙 문장" 확인을 통째로 건너뛴다 — 절이 없어도, 있어도, 규칙 꼴 파일을 고쳐도."""

    def setUp(self):
        super().setUp()
        self.ctx = Context(self.tmp, testing.make(testing.svc(rule_docs=None)))  # 설정 quest.rule_docs를 뺀 문맥(꺼짐)

    def change_rule_shaped(self):
        self.touch(".agents/rules/deps.md")
        self.commit("Q-061 fix: 규칙 꼴 파일", at(6))

    def test_without_section_passes(self):
        self.v2_finish(retro=V2_RETRO.replace("## 바뀐 규칙 문장\n\n- 없음\n\n", ""))
        self.assertEqual(self.end(), [])

    def test_with_section_passes_without_warning(self):
        self.v2_finish(retro=V2_RETRO.replace("## 바뀐 규칙 문장\n\n- 없음\n", "## 바뀐 규칙 문장\n\n- a.md:1 고침\n"))
        self.assertEqual(self.end(), [])
        self.assertEqual(checks.end_warnings(self.ctx, V2), [])

    def test_empty_section_passes(self):
        self.v2_finish(retro=V2_RETRO.replace("## 바뀐 규칙 문장\n\n- 없음\n", "## 바뀐 규칙 문장\n\n"))
        self.assertEqual(self.end(), [])

    def test_rule_shaped_change_does_not_block(self):
        self.v2_finish(retro=V2_RETRO.replace("## 바뀐 규칙 문장\n\n- 없음\n\n", ""))
        self.change_rule_shaped()
        self.assertEqual(self.end(), [])

    def test_same_change_blocks_when_on(self):
        """같은 저장소를 켠 설정(SVC — quest.rule_docs)으로 보면 막는다 — 켜고 끔이 설정에서만 온다."""
        self.v2_finish(retro=V2_RETRO.replace("## 바뀐 규칙 문장\n\n- 없음\n\n", ""))
        self.change_rule_shaped()
        found = checks.end_problems(Context(self.tmp, testing.make()), V2)
        self.assertIn("retro.md `## 바뀐 규칙 문장`이 비었다", found)
        self.assertTrue(any("규칙 문서를 바꿨는데" in x and "svc/.agents/rules/deps.md" in x for x in found), found)


class RunAfterPlanReviewTest(Base):
    """첫 `run:` 커밋은 첫 `plan-review:` 커밋 뒤. `test:`는 앞이어도 된다."""

    def finish(self, before_review):
        self.put(f"{V2_QUEST}/plan.md", V2_PLAN)
        self.commit("Q-061 plan: x", at(1))
        for tail, rel in before_review:
            self.touch(rel)
            self.commit(f"Q-061 {tail}", at(1))
        self.commit("Q-061 plan-review: x", at(2))
        done = {tail for tail, _ in before_review}
        for tail, rel in (("test: #1 a", TEST_JAVA), ("run: #1 a", MAIN_JAVA), ("test: #2 b", TEST_JAVA),
                          ("run: #2 b", MAIN_JAVA), ("run: #3 문서", "README.md")):
            if tail not in done:
                self.touch(rel)
                self.commit(f"Q-061 {tail}", at(3))
        self.put(f"{V2_QUEST}/review.md", V2_REVIEW)
        self.commit("Q-061 review: x", at(4))
        self.put(f"{V2_QUEST}/retro.md", V2_RETRO)
        self.commit("Q-061 done: x", at(5))

    def test_run_before_plan_review_blocks(self):
        self.finish([("test: #1 a", TEST_JAVA), ("run: #1 a", MAIN_JAVA)])
        self.assertTrue(any("코드 전 검토" in x and "구현 커밋" in x for x in self.end()), self.end())

    def test_chain_order_holds_for_every_step(self):
        """끝 확인의 차례 판정은 `quest step`과 같은 사슬(flow.json `chain`·`Flow.prerequisite`) — 첫 단계 커밋은 첫 앞 단계 커밋 뒤."""
        self.put(f"{V2_QUEST}/plan.md", V2_PLAN)
        self.commit("Q-061 plan: x", at(1))
        self.commit("Q-061 review: 너무 이름", at(1))
        self.finish([])
        found = self.end()
        self.assertTrue(any("④ 코드 뒤 검토" in x and "③ 구현" in x and "앞이다" in x for x in found), found)

    def test_tests_before_plan_review_pass(self):
        self.finish([("test: #1 a", TEST_JAVA), ("test: #2 b", TEST_JAVA)])
        self.assertEqual(self.end(), [])

    def test_without_plan_review_only_missing_step_is_reported(self):
        """plan-review 커밋이 없으면 이 검사는 쉰다 — "빠진 단계"가 막는다."""
        self.put(f"{V2_QUEST}/plan.md", V2_PLAN)
        self.commit("Q-061 plan: x", at(1))
        self.touch(MAIN_JAVA)
        self.commit("Q-061 run: #3 문서", at(2))
        found = self.end()
        self.assertFalse(any("코드 전 검토" in x and "구현 커밋" in x for x in found), found)
        self.assertTrue(any(x.startswith("빠진 단계") and "plan-review" in x for x in found), found)

    def test_doc_run_before_plan_review_blocks_too(self):
        self.finish([("run: #3 문서", "README.md")])
        self.assertTrue(any("코드 전 검토" in x and "구현 커밋" in x for x in self.end()), self.end())


class CloseLinesTest(Base):
    """장부는 리드만 쓴다 — 작업 세션은 장부 대신 retro `## 닫을 장부 줄`에 줄마다 한 줄을 적고, 끝 확인이 그 절을 본다.
    장부 줄은 작업 범위 밖(통합 브랜치 `dev/main`)에 커밋해 둔다 — 작업 세션이 장부를 고치지 않는 꼴."""

    def ledger(self, *rows):
        self.put("quests/carryover.md", LEDGER + "".join(f"| {c} | Q-050 | lead | 일 | {s} | {e} |\n" for c, s, e in rows))
        self.commit("lead: 장부", at(0))
        self.git("branch", "-f", "dev/main")  # 작업 범위 밖

    def retro(self, lines):
        return V2_RETRO.replace("## 닫을 장부 줄\n\n- 없음\n", "## 닫을 장부 줄\n\n" + lines)

    def close_problems(self):
        return [x for x in self.end() if "닫을 장부 줄" in x or "장부" in x]

    def test_left_line_without_close_line_blocks(self):
        self.ledger(("C-001", "요구사항 Q-061", "-"), ("C-002", "끝", "Q-061 abc1234"))
        self.v2_finish()
        found = self.end()
        self.assertTrue(any("C-001" in x and "`요구사항 Q-061`" in x and "## 닫을 장부 줄" in x for x in found), found)

    def test_close_lines_pass_and_ledger_stays(self):
        self.ledger(("C-001", "요구사항 Q-061", "-"), ("C-002", "요구사항 Q-061", "-"), ("C-003", "요구사항 Q-061", "-"),
                    ("C-004", "요구사항 Q-061", "-"), ("C-005", "요구사항 Q-050", "-"))
        self.v2_finish(retro=self.retro("- C-001: 끝 — Q-061 abc1234·test_edge\n- C-002: 열림 — Q-061 넘김 — 루트 .agents deny\n"
                                        "- C-003: 버림 — 과잉\n- C-004: 넘김 — msg 0123abcd\n"))
        self.assertEqual(self.end(), [])

    def test_bad_shape_and_proof_block(self):
        self.ledger(*[(f"C-00{i}", "요구사항 Q-061", "-") for i in range(1, 6)])
        cases = {"- C-001: 닫음 — x\n": "C-001: 닫음", "- C-001 끝 — x\n": "C-001 끝",
                 "- C-001: 끝 —  \n": "C-001", "- C-001: 넘김 — 보냈다\n": "보낸 근거",
                 "- C-001: 열림 — 나중에\n": "Q-061 넘김 —", "- C-001: 끝\n": "C-001: 끝"}
        for line, want in cases.items():
            with self.subTest(line=line):
                self.restore(_CACHE["base"])
                self.ledger(("C-001", "요구사항 Q-061", "-"))
                self.v2_finish(retro=self.retro(line))
                found = self.close_problems()
                self.assertTrue(any(want in x for x in found), (line, found))

    def test_unknown_or_other_work_line_blocks(self):
        self.ledger(("C-001", "요구사항 Q-061", "-"), ("C-002", "요구사항 Q-050", "-"), ("C-003", "끝", "Q-050 abc"))
        self.v2_finish(retro=self.retro("- C-001: 끝 — abc1234\n- C-002: 끝 — abc1234\n- C-003: 버림 — 과잉\n- C-009: 끝 — abc\n"))
        found = "\n".join(self.close_problems())
        self.assertIn("C-002", found)
        self.assertIn("C-003", found)
        self.assertIn("C-009", found)
        self.assertNotIn("C-001", found)

    def test_none_with_left_line_blocks_and_none_alone_passes(self):
        self.ledger(("C-001", "요구사항 Q-061", "-"))
        self.v2_finish()  # `- 없음`
        self.assertTrue(any("C-001" in x for x in self.close_problems()), self.end())
        self.restore(_CACHE["base"])
        self.ledger(("C-001", "요구사항 Q-050", "-"))
        self.v2_finish()
        self.assertEqual(self.end(), [])

    def test_line_closed_by_merge_record_passes(self):
        """합친 뒤(리드 기록 커밋이 장부를 고친 뒤)에는 같은 상태·근거로 닫힌 줄을 받는다 — 합치기의 두 번째 끝 확인."""
        self.ledger(("C-001", "요구사항 Q-061", "-"))
        self.v2_finish(retro=self.retro("- C-001: 끝 — Q-061 a|b\n"))
        self.put("quests/carryover.md", LEDGER + "| C-001 | Q-050 | lead | 일 | 끝 | Q-061 a\\|b |\n")
        self.commit("Q-061 merge: README 끝", at(6))
        self.assertEqual(self.close_problems(), [])
        self.put("quests/carryover.md", LEDGER + "| C-001 | Q-050 | lead | 일 | 버림 | 다른 근거 |\n")
        self.commit("Q-061 merge: README 끝", at(7))
        self.assertTrue(any("C-001" in x for x in self.close_problems()), self.end())

    def test_ledger_changed_in_work_range_blocks(self):
        self.ledger(("C-001", "요구사항 Q-061", "-"))
        self.v2_finish(retro=self.retro("- C-001: 끝 — abc1234\n"))
        self.put("quests/carryover.md", LEDGER + "| C-001 | Q-050 | lead | 일 | 끝 | abc1234 |\n")
        self.commit("Q-061 done: 장부", at(6))
        found = self.close_problems()
        self.assertTrue(any("장부는 리드가 합칠 때 고친다" in x for x in found), found)

    def test_unreadable_ledger_is_a_problem(self):
        """코드 뒤 검토 Minor: 장부를 못 읽으면 말없이 통과하지 않는다."""
        self.v2_finish()
        os.remove(os.path.join(self.wf, "quests", "carryover.md"))
        self.assertTrue(any("장부를 읽지 못했다" in x for x in self.end()), self.end())


if __name__ == "__main__":
    unittest.main()
