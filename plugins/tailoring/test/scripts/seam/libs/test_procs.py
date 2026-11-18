"""seam/libs/procs.py 시험 — 작업 세션 프로세스 찾기(pgrep 표지), 끝 확인 부르기."""
import os
import subprocess
import sys
import time
from unittest import mock

from seam.commands import join as m
from test.scripts.seam.commands.test_join import Repo  # 바탕(픽스처)


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ProcsTest(Repo):
    """작업 세션 프로세스 찾기와 새 프로세스 끝 확인."""

    def test_seam_check_must_pass(self):
        self.assertIsNone(m.seam_check_problem(self.wt, "P-077"))
        self.seam_check(1)
        problem = m.seam_check_problem(self.wt, "P-077")
        self.assertIn("끝 확인(inspect)이 통과하지 않는다", problem)
        self.assertIn("막힘", problem)
        self.assertIn("끝 확인(inspect)", str(self.main("P-077", "--keep")[0]))
        self.assertEqual(self.head_subject(), "base")

    def test_seam_check_runs_in_worktree(self):
        put(self.fake_check, "import os\nprint(os.getcwd())\nraise SystemExit(1)\n")
        self.assertIn(self.wt, m.seam_check_problem(self.wt, "P-077"))

    def test_session_pids_pattern(self):
        """이름 뒤는 빈칸이나 끝 — `piece P-07`이 `piece P-077`에 걸리지 않는다. 정규식 글자는 걷어 낸다."""
        import re
        pat = m.name_pattern("piece P-07")
        self.assertTrue(re.search(pat, "claude --name piece P-07 --settings x"))
        self.assertTrue(re.search(pat, "claude --name piece P-07"))
        self.assertFalse(re.search(pat, "claude --name piece P-077 --settings x"))
        self.assertEqual(m.name_pattern("a.b (x)"), r"--name a\.b \(x\)( |$)")
        with mock.patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="12\n34\n")) as run:
            self.assertEqual(self.real_session_pids("piece P-077"), ["12", "34"])
        self.assertEqual(run.call_args[0][0], ["pgrep", "-f", "--", "--name piece P-077( |$)"])
        with mock.patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, stdout="")):
            self.assertEqual(self.real_session_pids("x"), [])
        with mock.patch.object(m.subprocess, "run", side_effect=OSError("없음")):
            self.assertEqual(self.real_session_pids("x"), [])

    def test_session_pids_finds_real_process(self):
        """진짜 프로세스 하나를 같은 표지로 띄워 찾는다(pgrep이 있을 때)."""
        import shutil
        if not shutil.which("pgrep"):
            self.skipTest("pgrep 없음")
        title = f"seamtest-{os.getpid()} X"
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "--name", title])
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        found = []
        for _ in range(50):
            found = self.real_session_pids(title)
            if found:
                break
            time.sleep(0.1)
        self.assertIn(str(proc.pid), found)
        self.assertEqual(self.real_session_pids(title[:-1]), [])  # 앞부분만 같은 이름은 아니다

    def test_session_running_reads_pgrep(self):
        with mock.patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(self.real_session_running("/x/P-077/settings.json"))
        self.assertEqual(run.call_args[0][0], ["pgrep", "-f", "/x/P-077/settings.json"])
        with mock.patch.object(m.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(self.real_session_running("x"))
        with mock.patch.object(m.subprocess, "run", side_effect=OSError("없음")):
            self.assertFalse(self.real_session_running("x"))


if __name__ == "__main__":
    unittest.main()
