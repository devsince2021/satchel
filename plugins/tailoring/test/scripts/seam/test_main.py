"""seam/main.py 시험 — 입구 자리·부명령 나눔·종료 코드를 진짜 프로세스로."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from test import helpers as testing


HOOKS_JSON = os.path.join(testing.PLUGIN, "src", "hooks", "hooks.json")


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout


MINIMAL = {"branches": {"integration": "main"}, "session": {"terminal": "none"}}  # 필수 둘만


class Repo(unittest.TestCase):
    """필수 둘만 적은 설정(나머지는 기본값) 저장소 — 통합 브랜치 `main`, 작업 P-001(기록 `.agents/pieces/P-001-sample`)."""
    CONFIG = MINIMAL

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.realpath(self.tmp.name)
        git(self.repo, "init", "-q", "-b", "main")
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"), ("gc.auto", "0"), ("maintenance.auto", "false")):
            git(self.repo, "config", k, v)
        if self.CONFIG is not None:
            testing.write(self.repo, self.CONFIG)
        seam = os.path.join(self.repo, ".agents", "pieces", "P-001-sample")
        os.makedirs(seam)
        with open(os.path.join(seam, "requirements.md"), "w", encoding="utf-8") as f:
            f.write("# r\n\n- 작업: P-001 · 흐름: seam\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "P-001 req: 요구사항")

    def seam(self, *args, cwd=None, stdin=None):
        out = subprocess.run([sys.executable, testing.SEAM, *args], cwd=cwd or self.repo, input=stdin,
                             capture_output=True, text=True)
        return out.returncode, out.stdout, out.stderr

    def hook_command(self, payload):
        """hooks.json의 명령 그대로(셸, `${CLAUDE_PLUGIN_ROOT}` = 플러그인 자리)."""
        with open(HOOKS_JSON, encoding="utf-8") as f:
            command = json.load(f)["hooks"]["Stop"][0]["hooks"][0]["command"]
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=testing.PLUGIN)
        out = subprocess.run(["sh", "-c", command], input=json.dumps(payload), env=env, capture_output=True, text=True,
                             cwd=payload.get("cwd"))
        return out.returncode, out.stdout, out.stderr


class EntryTest(Repo):
    def test_entry_is_main_py_under_scripts(self):
        """입구는 `src/scripts/seam/main.py`(첫 줄 python3 shebang, 실행 권한) — 세션 PATH에 싣는 명령 폴더는 없다(스킬·훅이 전체 경로로 부른다).
        실행 권한으로 직접 불러도, 다른 자리에서 불러도 돈다."""
        self.assertEqual(os.path.dirname(testing.SEAM), os.path.join(testing.PLUGIN, "src", "scripts", "seam"))
        self.assertFalse(os.path.exists(os.path.join(testing.PLUGIN, "bin")))
        self.assertTrue(os.access(testing.SEAM, os.X_OK))
        with open(testing.SEAM, encoding="utf-8") as f:
            self.assertEqual(f.readline(), "#!/usr/bin/env python3\n")
        self.assertEqual(sorted(os.listdir(os.path.join(testing.PLUGIN, "src"))), ["hooks", "presets", "rules", "scripts", "skills"])
        self.assertEqual(sorted(d for d in os.listdir(os.path.join(testing.PLUGIN, "src", "scripts")) if d != "__pycache__"),
                         ["deliver", "libs", "seam"])  # 코드는 src/scripts/ 아래
        out = subprocess.run([testing.SEAM, "status", "P-001"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("req\t"), out.stdout)

    def test_unknown_or_no_command(self):
        for args in ((), ("finish", "P-001"), ("seam_check",)):
            code, out, _ = self.seam(*args)
            self.assertEqual(code, 2, args)
            self.assertIn(f"쓰는 법: python3 {os.path.realpath(testing.SEAM)} feed|step|status|inspect|base|join|carryover|hold|guard|rules-doc", out)

    def test_old_hook_command_names_are_unknown(self):
        """옛 이름(훅이 불리는 때로 지은 이름)은 별칭으로 남기지 않는다 — 모르는 부명령으로 2, 판정 모듈을 부르지 않는다."""
        old_names = ("pre" + "-tool", "stop" + "-hook")  # 저장소 grep에 옛 이름이 남지 않게 나눠 쓴다
        for name in old_names:
            code, out, err = self.seam(name, stdin="{}")
            self.assertEqual(code, 2, name)
            self.assertTrue(out.startswith("쓰는 법: python3 "), out)
            self.assertEqual(err, "", name)

    def test_status_end_base(self):
        code, out, _ = self.seam("status", "P-001")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("req\t"), out)
        self.assertIn("빠진 단계: plan, plan-review, run, review, done", out)
        code, out, _ = self.seam("inspect", "P-001")
        self.assertEqual(code, 1)
        self.assertTrue(out.endswith("seam_check: 막힘\n"), out)
        code, out, _ = self.seam("base", "P-001")
        self.assertEqual((code, out.strip()), (0, git(self.repo, "rev-parse", "HEAD").strip()))

    def test_bad_id_and_outside_git(self):
        code, out, _ = self.seam("inspect", "X-1")
        self.assertEqual((code, out), (2, f"쓰는 법: python3 {testing.SEAM} inspect P-NNN\n"))
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.assertEqual(self.seam("status", "P-001", cwd=outside.name)[:2], (2, "seam_check: git 작업본 안에서 부른다\n"))

    def test_bad_config_is_exit_2(self):
        with open(os.path.join(self.repo, ".studio", "tailoring.json"), "w", encoding="utf-8") as f:
            f.write('{"nope": 1}')
        self.assertEqual(self.seam("inspect", "P-001")[:2], (2, "seam_check: 설정 오류: 모르는 키: nope\n"))
        self.assertEqual(self.seam("carryover")[:2], (2, "check_carryover: 설정 오류: 모르는 키: nope\n"))

    def test_open_and_merge_usage(self):
        code, _, err = self.seam("feed")
        self.assertEqual(code, 2)
        self.assertIn("usage: seam feed", err)
        code, _, err = self.seam("join")
        self.assertEqual(code, 1)
        self.assertIn("<seam> join <ID>", err)

    def test_open_dry_run_without_hook(self):
        with open(os.path.join(self.repo, ".agents", "pieces", "README.md"), "w", encoding="utf-8") as f:
            f.write("## 작업 목록\n\n| ID | 작업 | 상태 | 결정 |\n| --- | --- | --- | --- |\n| P-001 | t | 진행 | 0011~0020 |\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "목록")
        code, out, _ = self.seam("feed", "P-001", "--lead", "lead-session", "--dry-run")
        self.assertEqual(code, 0, out)
        got = json.loads(out)
        self.assertEqual(list(got["settings_body"]), ["permissions"])
        self.assertEqual(got["branch"], "piece/P-001-sample")


if __name__ == "__main__":
    unittest.main()
