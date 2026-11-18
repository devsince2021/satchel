"""seam/commands/hold.py 시험 — Stop 훅: `대기: 사용자`·반복 막힘·깨우기 예약, 같은 멈춤 두 번 부름."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from test import helpers as testing
from seam.libs import stop as stop_wait
from seam.commands import hold as hold_cmd


def tool_use(name, **inp):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": name, "name": name, "input": inp}]}}


ASK = tool_use("SendMessage", to="lead", message="[P-077 → lead] 결정 요청: svc/.agents/workflow/pieces/P-077-x/asks-1.md")


WAKE = tool_use("ScheduleWakeup", delaySeconds=1500, reason="결정 요청 답 기다림", prompt="이어 간다")


class StopWaitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.realpath(self.tmp.name)
        os.makedirs(os.path.join(self.repo, "svc", ".agents", "workflow"))
        subprocess.run(["git", "init", "-q", "-b", "piece/P-077-sample", self.repo], check=True)
        testing.write(self.repo)
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write(".studio/\n")  # 설정 파일이 깨끗함 검사에 걸리지 않게
        p = mock.patch.object(stop_wait, "STATE_FILE", os.path.join(self.repo, "count.json"))
        p.start()
        self.addCleanup(p.stop)

    def run_hook(self, message, active=False, cwd=None):
        payload = {"cwd": cwd or self.repo, "last_assistant_message": message, "stop_hook_active": active}
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stderr(err):
            code = hold_cmd.main()
        return code, err.getvalue()

    def test_user_wait_is_returned(self):
        code, err = self.run_hook("다 했다\n남은 지시: 결정 하나\n대기: 사용자 — 결정")
        self.assertEqual(code, 2)
        self.assertIn("결정 요청", err)
        self.assertIn("[P-NNN → lead]", err)

    def test_last_wait_line_counts(self):
        self.assertEqual(self.run_hook("대기: 사용자\n대기: 리드 — 결정 요청")[0], 0)
        self.assertEqual(self.run_hook("대기: 리드\n대기: 사용자 확인")[0], 2)

    def test_other_waits_pass(self):
        for msg in ("대기: 리드 — 결정 요청", "대기: 백그라운드 — 시험", "끝", ""):
            self.assertEqual(self.run_hook(msg)[0], 0, msg)

    def test_give_up_only_after_three_returns(self):
        msg = "대기: 사용자"
        self.assertEqual(self.run_hook(msg)[0], 2)
        self.assertEqual(self.run_hook(msg, active=True)[0], 2)
        early = self.run_hook("대기: 리드 — 반복 막힘", active=True)
        self.assertEqual(early[0], 2)
        self.assertIn("3회", early[1])
        code, err = self.run_hook(msg, active=True)
        self.assertEqual(code, 2)
        self.assertIn("3회 되돌렸다", err)
        self.assertEqual(self.run_hook("대기: 리드 — 반복 막힘", active=True)[0], 0)

    def test_count_restarts_without_stop_hook_active(self):
        for _ in range(3):
            self.run_hook("대기: 사용자", active=True)
        self.run_hook("대기: 사용자", active=False)
        self.assertEqual(self.run_hook("대기: 리드 — 반복 막힘", active=True)[0], 2)

    def test_lead_branch_passes_and_every_work_number_is_judged(self):
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "dev/main"], check=True)
        self.assertEqual(self.run_hook("대기: 사용자")[0], 0)
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", "piece/P-005-old"], check=True)
        self.assertEqual(self.run_hook("대기: 사용자")[0], 2)  # 번호로 가르는 옛 작업 갈래가 없다

    def test_default_count_file_lives_in_git_dir(self):
        """횟수 파일은 git 자리에 둬서 워크트리를 더럽히지 않는다(합치기 전 깨끗함 검사)."""
        with mock.patch.object(stop_wait, "STATE_FILE", None):
            self.assertEqual(self.run_hook("대기: 사용자")[0], 2)
            self.assertTrue(os.path.exists(os.path.join(self.repo, ".git", "stop-wait.json")))
            status = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
            self.assertEqual(status, "")
            self.assertEqual(self.run_hook("대기: 리드 — 결정 요청")[0], 0)
            self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "stop-wait.json")))

    def test_outside_git_passes_silently(self):
        """플러그인 훅은 모든 세션에서 불린다 — git 밖 자리에서는 아무것도 하지 않고 0(횟수 파일 자리를 찾다 넘어지지 않는다)."""
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with mock.patch.object(stop_wait, "STATE_FILE", None):
            self.assertEqual(self.run_hook("대기: 사용자", cwd=os.path.realpath(outside.name)), (0, ""))

    def test_broken_input_passes(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("{")), redirect_stderr(err):
            self.assertEqual(hold_cmd.main(), 0)
        self.assertIn("판정 불가로 통과", err.getvalue())


class WakeAfterAskTest(StopWaitTest):
    """`대기: 리드 — 결정 요청`으로 끝내면 기록(transcript_path)에서 마지막 결정 요청 뒤
    30분 안 깨우기 예약(ScheduleWakeup ≤ 1800초, stop 아님 · CronCreate)을 본다. 기록을 못 읽으면 판정 불가 통과."""

    MSG = "결정 요청을 보냈다\n대기: 리드 — 결정 요청"

    def transcript(self, *entries):
        path = os.path.join(self.repo, "t.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "시작"}}) + "\n")
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return path

    def hook(self, *entries, message=None, path=None):
        payload = {"cwd": self.repo, "last_assistant_message": message or self.MSG, "stop_hook_active": False,
                   "transcript_path": path or self.transcript(*entries)}
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stderr(err):
            code = hold_cmd.main()
        return code, err.getvalue()

    def test_ask_then_wake_passes(self):
        self.assertEqual(self.hook(ASK, WAKE)[0], 0)
        cron = tool_use("CronCreate", cron="*/30 * * * *", prompt="이어 간다", recurring=False)
        self.assertEqual(self.hook(ASK, cron)[0], 0)

    def test_ask_through_bash_does_not_count(self):
        """결정 요청 보냄은 SendMessage만 — 셸 명령 속 `결정 요청` 글은 보냄이 아니다."""
        bash = tool_use("Bash", command="relay send --to x '[P-077 → lead] 결정 요청: a/asks-1.md'")
        code, err = self.hook(bash, WAKE)
        self.assertEqual(code, 2)
        self.assertIn("결정 요청을 보낸 기록이 없다", err)

    def test_ask_without_wake_blocks(self):
        code, err = self.hook(ASK)
        self.assertEqual(code, 2)
        self.assertIn("깨우기 예약", err)

    def test_wake_before_ask_does_not_count(self):
        self.assertEqual(self.hook(WAKE, ASK)[0], 2)

    def test_wake_longer_than_thirty_minutes_blocks(self):
        late = tool_use("ScheduleWakeup", delaySeconds=3600, reason="r", prompt="p")
        self.assertEqual(self.hook(ASK, late)[0], 2)

    def test_stopping_wake_does_not_count(self):
        self.assertEqual(self.hook(ASK, tool_use("ScheduleWakeup", stop=True))[0], 2)

    def test_no_ask_sent_blocks(self):
        code, err = self.hook(WAKE)
        self.assertEqual(code, 2)
        self.assertIn("결정 요청", err)

    def test_unreadable_transcript_passes(self):
        code, err = self.hook(path=os.path.join(self.repo, "없음.jsonl"))
        self.assertEqual(code, 0)
        self.assertIn("기록을 못 읽어", err)  # 코드 뒤 검토 Important — 판정이 꺼진 것을 남긴다

    def test_wake_from_before_the_last_user_turn_does_not_count(self):
        """코드 뒤 검토 Important — 깨어난 턴 뒤 새 예약 없이 다시 결정 요청 대기로 끝내면 되돌린다."""
        woke = {"type": "user", "message": {"role": "user", "content": "이어 간다"}}
        self.assertEqual(self.hook(ASK, WAKE, woke)[0], 2)
        self.assertEqual(self.hook(ASK, WAKE, woke, WAKE)[0], 0)

    def test_hook_feedback_and_tool_results_are_not_user_turns(self):
        fed = {"type": "user", "message": {"role": "user", "content": "Stop hook feedback:\n[stop_wait] x"}}
        result = {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}}
        self.assertEqual(self.hook(ASK, WAKE, fed, result)[0], 0)

    def test_other_waits_do_not_look_at_transcript(self):
        self.assertEqual(self.hook(message="끝\n대기: 백그라운드 — 시험")[0], 0)


class DoubleCallTest(unittest.TestCase):
    """같은 멈춤에 훅이 두 번 불려도(같은 플러그인이 홈 설치와 `--plugin-dir` 둘로 실림) 되돌림 횟수는 한 번만 센다.
    열쇠는 훅 입력의 세션 id와 기록 파일 크기 — 되돌린 뒤의 다음 멈춤은 기록이 늘어 새로 센다."""

    def setUp(self):
        StopWaitTest.setUp(self)  # 같은 저장소 꼴(StopWaitTest의 시험은 다시 돌리지 않는다)
        self.path = os.path.join(self.repo, ".git", "t.jsonl")
        self.grow()

    def grow(self):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": []}}) + "\n")

    def call(self, active):
        payload = {"cwd": self.repo, "last_assistant_message": "대기: 사용자", "stop_hook_active": active,
                   "transcript_path": self.path, "session_id": "s1"}
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stderr(err):
            return hold_cmd.main(), err.getvalue()

    def count(self):
        with open(os.path.join(self.repo, "count.json"), encoding="utf-8") as f:
            return json.load(f)["count"]

    def test_same_stop_counts_once(self):
        for active in (False, True, True):
            self.assertEqual(self.call(active)[0], 2)
            self.assertEqual(self.call(active)[0], 2)  # 같은 멈춤의 두 번째 부름
            self.grow()  # 되돌린 뒤 다음 멈춤
        self.assertEqual(self.count(), 3)  # 여섯 번 불렸지만 멈춤은 셋

    def test_without_transcript_counts_each_call(self):
        """기록 자리가 없으면 열쇠가 없어 예전대로 부름마다 센다."""
        os.remove(self.path)
        self.call(False)
        self.call(True)
        self.assertEqual(self.count(), 2)


if __name__ == "__main__":
    unittest.main()
