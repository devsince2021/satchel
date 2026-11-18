"""부명령 `feed` — 리드 세션이 seam 작업 세션을 연다. 리드 체크아웃(설정 `branches.integration`) 안에서 부른다.

  <seam> feed <ID> --lead <리드 세션 이름>               # 연다
  <seam> feed <ID> --lead <이름> --dry-run               # 할 일·settings만 보인다
  <seam> feed <ID> --lead <이름> --check-only            # 확인만
  <seam> feed <ID> --lead <이름> --open <폴더>           # 막힌 자리 안 한 폴더만 열어 준다(여러 번)

⓪ 요구사항(`<설정 seam.pieces>/<ID>-<슬러그>/requirements.md`)과 작업 목록 줄, 설정 파일(`.studio/tailoring.json`)이 커밋돼 있어야 한다.
차례: 규칙·설정 읽기 → 자리 셈과 열기 전 확인(`seam/libs/workspace.py`) → 브랜치·워크트리 → 세션 기록 자리에 세션 settings(deny —
`seam/libs/deny.py`)·시작 지시·상시 프롬프트·지시 장부(`seam/libs/prompts.py`)·기록 `session.json` → 세션 띄우기(설정
`session.terminal`의 프리셋 또는 custom 틀 — `seam/libs/terminals.py`, `none`이면 명령을 찍는다) → 기록에 터미널·핸들.
여는 도중 실패하면 정리 명령을 찍는다. 훅은 세션 settings에 넣지 않는다 — 플러그인 훅(`src/hooks/hooks.json`)이 건다.
"""
import argparse
import json
import os
import sys
from datetime import datetime

from seam.libs import config, deny, prompts, rules, workspace
from seam.libs import terminals as terminal
from seam.libs.context import Context


def fail(p, message):
    sys.exit(f"{message}\n{workspace.cleanup_hint(p)}")


def write(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def main(argv):
    parser = argparse.ArgumentParser(prog="seam feed", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("work")
    parser.add_argument("--lead", default="", help="리드 세션 이름(작업 세션이 SendMessage로 보낼 이름)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--open", action="append", default=[], metavar="폴더",
                        help="막힌 자리(규칙 src/rules/files.json paths의 <자리>/**) 안 한 폴더만 연다 — 형제는 하나씩 막는다(여러 번)")
    args = parser.parse_args(argv)
    root = config.project_root(os.getcwd())
    if not root:
        sys.exit("git 작업본(리드 체크아웃) 안에서 부른다.")
    try:
        rules.load_all()  # 규칙 파일이 깨졌으면 아무것도 하기 전에 멈춘다
        cfg = Context(root).cfg
        p = workspace.plan(args.work, args.lead, root, cfg)
        p["open"] = args.open
        problems = workspace.check_lead(p, cfg)
        p["command"] = workspace.launch_command(p, cfg)
        launch_line = terminal.launch_line(cfg.terminal, cfg, p)
    except config.ConfigError as e:
        sys.exit(f"설정 오류: {e}")
    except rules.RuleError as e:
        sys.exit(f"규칙 오류: {e}")
    settings = deny.session_settings(p, cfg)
    if args.dry_run:
        print(json.dumps({**p, "settings_body": settings, "launch": launch_line, "problems": problems},
                         ensure_ascii=False, indent=2))
        return 0
    if problems:
        sys.exit("\n".join(problems))
    if args.check_only:
        print("check_lead 통과")
        return 0
    workspace.git("worktree", "add", "-b", p["branch"], p["worktree"], cfg.integration, cwd=root)
    os.makedirs(p["session_dir"], exist_ok=True)
    write(p["settings"], json.dumps(settings, ensure_ascii=False, indent=2))
    write(p["prompt_file"], prompts.task_text(p, cfg))
    write(p["standing"], prompts.standing_text(p, cfg))
    os.makedirs(os.path.dirname(p["orders"]), exist_ok=True)
    write(os.path.join(os.path.dirname(p["orders"]), ".gitignore"), "*\n")
    write(p["orders"], prompts.orders_text(p))
    if workspace.git("status", "--porcelain", cwd=p["worktree"]):
        fail(p, f"워크트리에 git이 잡는 파일이 생겼다 — {workspace.ORDERS_DIR}/.gitignore를 확인한다.")
    record_path = os.path.join(p["session_dir"], "session.json")
    record = {**p, "handle": None, "session_name": None, "opened": datetime.now().isoformat(timespec="seconds")}
    write(record_path, json.dumps(record, ensure_ascii=False, indent=2))
    try:
        launched = terminal.launch(cfg.terminal, cfg, p)
    except (terminal.TerminalError, config.ConfigError) as e:
        fail(p, str(e))
    if launched is not None:
        record["handle"] = launched["handle"]
        if launched["note"]:
            record["launch_note"] = launched["note"]
        write(record_path, json.dumps(record, ensure_ascii=False, indent=2))
    print(json.dumps({"work": p["work"], "terminal": cfg.terminal, "handle": record["handle"], "branch": p["branch"],
                      "worktree": p["worktree"], "record": record_path}, ensure_ascii=False))
    if launched is not None and launched["note"]:
        print(f"경고: {launched['note']}")
    for line in prompts.after_open_lines(p, cfg, launched is not None):
        print(line)
    return 0
