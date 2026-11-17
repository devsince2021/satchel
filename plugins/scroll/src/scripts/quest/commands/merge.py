"""부명령 `merge` — 리드 세션이 끝난 quest 작업을 통합 브랜치(설정 `branches.integration`)에 합치고 치운다. 리드 체크아웃 안에서 부른다.

  <quest> merge <ID>                     # 합치고 치운다
  <quest> merge <ID> --dry-run           # 할 일만 보인다
  <quest> merge <ID> --keep              # 합치기만, 세션·워크트리·브랜치는 둔다
  <quest> merge <ID> --verified "<메모>"  # 기록 커밋 본문 `메모:` 줄(판정 근거 아님)

단계(정본 `src/rules/flow.json`의 `merge`, 이 파일이 그 차례로 돈다):
① 확인 — 세션 기록(`<git 공통 자리>/satchel/quest-sessions/<ID>/session.json`), 작업 세션 프로세스 없음(`claude --name <세션 이름>`을
   `pgrep -f`로 — 있으면 pid와 함께 멈춘다), 워크트리 있음, 워크트리에서 끝 확인(`end`) 통과.
② deliver — `src/scripts/deliver/steps.py`로 넣기: 리베이스 → 프로젝트 검사(설정 `deliver.verify`, 비면 건너뜀) → 합치기 전에 기록 커밋
   (`quest/libs/record.py` — 작업 목록 `끝`·장부 번호·회고 `## 닫을 장부 줄`대로 장부 줄 닫기, 못 하면 멈춤)과 끝 확인 다시 → fast-forward. 그 뒤 (켜졌으면) 회고 `## 바뀐 규칙 문장` 줄을 찍는다.
③ 치우기 — 세션 닫기(`quest/libs/terminals.py`)·claude 멈춤 기다림 → 워크트리 지우기 → 브랜치 지우기 → 세션 기록을 `<자리>/done/`으로.
멈추면 `quest merge — <단계>에서 멈춤: …`(`<quest>` = `python3 <플러그인 뿌리>/src/scripts/quest/main.py`). 고치고 다시 부른다(한 단계는 다시 해도 같다). 푸시는 하지 않는다.
"""
import json
import os
import shutil
import subprocess  # noqa: F401  시험이 이 모듈의 subprocess.run을 바꾼다(프로세스 찾기)
import sys
import time
from datetime import datetime

from deliver import steps as deliver
from libs import git as gitlib
from quest.libs import config, procs, record
from quest.libs import rules as flow_rules
from quest.libs import terminals as terminal
from quest.libs.context import Context
from quest.libs.procs import name_pattern, session_pids, session_running  # 시험이 이 이름들을 바꾼다

QUEST = config.ENTRY  # 끝 확인을 부를 입구(src/scripts/quest/main.py)


def stop(stage, reason):
    """멈춘 단계(흐름 규칙 merge의 문서 이름)와 까닭으로 끝낸다(종료 1)."""
    sys.exit(f"quest merge — {flow_rules.flow().merge_stage(stage)}에서 멈춤: {reason}")


def say(stage, text):
    print(f"[{flow_rules.flow().merge_stage(stage)}] {text}")


def quest_check_problem(worktree, work):
    """작업 워크트리에서 끝 확인이 통과하지 않으면 그 출력, 통과면 None(시험이 바꾼다)."""
    return procs.end_check_problem(QUEST, worktree, work)


def steps(s, keep, cfg):
    """`--dry-run`이 찍는 차례 — 단계마다 머리 줄."""
    flow = flow_rules.flow()
    check = f"(워크트리에서) python3 {QUEST} end {s['work']}"
    title = s.get("title") or cfg.title_for(s["work"])
    out = [f"[{flow.merge_stage('check')}]",
           f"작업 세션 프로세스 없음: pgrep -f -- '{name_pattern(title)}'  (있으면 멈춘다 — 세션을 끝낸 뒤 다시 부른다)",
           f"{check}  (통과)",
           f"[{flow.merge_stage('deliver')}]"]
    out += deliver.plan_lines(s["lead_top"], s["branch"], cfg.integration, cfg.get("deliver.verify"), s["worktree"], before_merge_lines=(
        f"기록 커밋 {record.merge_title(s['work'])} README 끝(<마지막 작업 커밋>, 로컬)·넘길 일 {cfg.carry_prefix} 번호(장부, retro [{cfg.carry_shape}])"
        "·장부 줄 닫기(retro ## 닫을 장부 줄 — 읽지 못하거나 요구사항 줄이 남으면 멈춘다)",
        f"{check}  (기록 뒤 다시 통과)"))
    if cfg.rule_docs.on:
        out.append("회고 ## 바뀐 규칙 문장 줄을 그대로 출력(리드가 보고에 옮긴다, 없으면 '바뀐 규칙 문장: 없음')")
    if not keep:
        out += [f"[{flow.merge_stage('cleanup')}]", *record.close_lines(s, cfg),
                "작업 세션 claude가 멈출 때까지 기다림(pgrep -f <세션 settings 경로>)",
                f"git -C {s['lead_top']} worktree remove {s['worktree']}", f"git -C {s['lead_top']} branch -d {s['branch']}",
                f"mv {s['session_dir']} {os.path.join(os.path.dirname(s['session_dir']), 'done', s['work'])}"]
    return out


VALUE_OPTS = ("verified",)


def split_opts(argv):
    """값을 받는 인자(`--verified`, `=` 꼴도)를 떼어 낸다 → (값 사전, 나머지)."""
    opts, rest, it = dict.fromkeys(VALUE_OPTS), [], iter(argv)
    for a in it:
        name = a[2:].partition("=")[0] if a.startswith("--") else None
        if name in VALUE_OPTS:
            opts[name] = a.partition("=")[2] if "=" in a else next(it, "")
        else:
            rest.append(a)
    return opts, rest


def check(s, work, title):
    """① 확인."""
    for warning in record.record_warnings(s):
        print(warning)
    pids = session_pids(title)
    if pids:
        stop("check", f"작업 세션이 아직 돈다(claude --name {title}, pid {' '.join(pids)}) — 세션을 끝낸 뒤 다시 부른다.")
    if not os.path.isdir(s["worktree"]):
        stop("check", f"워크트리가 없다: {s['worktree']}")
    problem = quest_check_problem(s["worktree"], work)
    if problem:
        stop("check", problem)
    say("check", "작업 세션 멈춤, 끝 확인 통과")


def put_in(s, work, cfg, memo):
    """② deliver — 합치기 전에 기록 커밋과 끝 확인 다시."""
    verify = cfg.get("deliver.verify")
    body = [f"리드 끝 검증: {verify} → 통과"] if verify else []
    body += [f"메모: {memo}"] if memo else []

    def before_merge(worktree):
        try:
            title = record.write_record(s, work, cfg, body)
        except gitlib.GitError as e:
            return f"기록 커밋 실패: {e}"
        except record.RecordError as e:
            return f"장부 줄 닫기 실패: {e}"
        if title:
            print(f"기록: {title}")
        return quest_check_problem(worktree, work)

    say("deliver", f"{s['branch']} → {cfg.integration}" + (f", 검사 {verify}" if verify else ", 검사 없음(deliver.verify 비어 있음)"))
    try:
        deliver.deliver(s["lead_top"], s["branch"], cfg.integration, verify, worktree=s["worktree"], before_merge=before_merge)
    except deliver.Stop as e:
        stop("deliver", f"{e.stage} — {e.reason}")
    if cfg.rule_docs.on:
        print(record.rule_change_report(s["worktree"], work, cfg))


def clean_up(s, work, cfg):
    """③ 치우기."""
    try:
        for warning in terminal.close(s, cfg):
            print(warning)
    except config.ConfigError as e:  # custom 닫기 틀의 모르는 자리표 — 병합은 끝났으니 알리고 치우기는 이어 간다
        print(f"경고: 세션 닫기 틀 오류: {e}")
    marker = s.get("settings") or os.path.join(s["session_dir"], "settings.json")  # claude 명령 줄에 세션 settings 경로가 있다(open)
    for _ in range(20):
        if not session_running(marker):
            break
        time.sleep(1)
    else:
        stop("cleanup", f"작업 세션 claude가 아직 돈다(pgrep -f {marker}). 세션을 끝낸 뒤 python3 {QUEST} merge {work}를 다시 부른다(병합은 끝났다).")
    try:
        gitlib.run(s["lead_top"], "worktree", "remove", s["worktree"])
        gitlib.run(s["lead_top"], "branch", "-d", s["branch"])
    except gitlib.GitError as e:
        stop("cleanup", str(e))
    target = os.path.join(os.path.dirname(s["session_dir"]), "done", work)
    if os.path.exists(target):
        target += "-" + datetime.now().strftime("%Y%m%d%H%M%S")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(s["session_dir"], target)
    say("cleanup", f"워크트리 {s['worktree']} 지움, 브랜치 {s['branch']} 지움, 세션 기록 → {target}")


def main(argv):
    opts, argv = split_opts(argv)
    args = [a for a in argv if not a.startswith("--")]
    root = config.project_root(os.getcwd())
    if not root:
        sys.exit("git 작업본(리드 체크아웃) 안에서 부른다.")
    try:
        cfg = Context(root).cfg
        records = cfg.records_dir(root)
        flow_rules.load_all()  # 규칙 파일이 깨졌으면 아무것도 하기 전에 멈춘다
    except config.ConfigError as e:
        sys.exit(f"설정 오류: {e}")
    except flow_rules.RuleError as e:
        sys.exit(f"규칙 오류: {e}")
    if len(args) != 1 or not cfg.is_id(args[0]):
        sys.exit(__doc__)
    work = args[0]
    record_path = os.path.join(records, work, "session.json")
    if not os.path.exists(record_path):
        sys.exit(f"세션 기록이 없다: {record_path}")
    with open(record_path, encoding="utf-8") as f:
        s = json.load(f)
    keep = "--keep" in argv
    if "--dry-run" in argv:
        print("\n".join(steps(s, keep, cfg)))
        return 0
    check(s, work, s.get("title") or cfg.title_for(work))
    put_in(s, work, cfg, opts["verified"])
    if not keep:
        clean_up(s, work, cfg)
    return 0
