"""작업 자리 셈과 열기 전 확인 — 부명령 `open`(`quest/commands/open.py`)이 쓴다.

- `plan`: 작업 하나의 이름·자리(브랜치 `quest/<ID>-<슬러그>`, 워크트리 `<리드 저장소 부모>/<저장소>-<id 소문자>`, 세션 기록 자리
  `<git 공통 자리>/satchel/quest-sessions/<ID>/`의 settings·`task.md`·`standing.md`, 워크트리 `.quest-session/orders.md`).
  세션 기록(`session.json`)이 되는 사전이다 — PreToolUse·Stop 훅은 그 `lead_top`·`worktree`·`settings`·`home`·`block_git`·
  `block_git_args`·`standing`·`orders`를 읽는다. guard 목록(block_git·block_git_args)은 플러그인 규칙 `src/rules/git.json`에서 만든다.
- `check_lead`: 열기 전 확인(리드 체크아웃 브랜치, 요구사항·작업 목록·설정 파일 커밋, 통합 브랜치의 `<ID> req:` 커밋, 요구사항 틀, 브랜치·워크트리 자리, 훅 파일,
  터미널 프리셋의 실행 파일·환경 변수, 워크트리 자리가 리드 저장소 밖인지).
- `launch_command`: 작업 세션을 띄우는 셸 한 줄 — 늘 `claude --model <설정 session.model> --dangerously-skip-permissions --plugin-dir <이 플러그인>`.
"""
import glob
import os
import re
import shlex
import subprocess
import sys

from quest.libs import config, rules
from quest.libs import terminals as terminal
from quest.libs.checks import requirements  # 요구사항 틀 확인
from quest.libs.deny import open_problems


def quest_entry(p):
    """작업 세션이 부를 입구 — 세션 기록의 플러그인 뿌리(`--plugin-dir`로 싣는 그 자리)의 src/scripts/quest/main.py.
    세션 PATH에 싣는 입구는 없으므로 시작 지시는 이 전체 경로를 쓴다."""
    return os.path.join(p["plugin_root"], "src", "scripts", "quest", "main.py")


HOOKS_JSON = os.path.join(config.PLUGIN_ROOT, "src", "hooks", "hooks.json")  # Stop·PreToolUse 훅을 거는 플러그인 훅


STANDING = "standing.md"  # 상시 프롬프트(세션 기록 자리) — Stop 훅이 턴 끝 줄 없이 멈추면 다시 넣는다


ORDERS_DIR = ".quest-session"  # 워크트리 안 지시 장부 자리 — 안의 `.gitignore`(`*`)로 git이 잡지 않는다(깨끗함 검사에 안 걸림)


ORDERS = "orders.md"  # 지시 장부 — 작업 세션이 고친다(세션 기록 자리는 deny라 워크트리에 둔다)


def run(cmd, check=True):
    out = subprocess.run(cmd, capture_output=True, text=True)
    if check and out.returncode != 0:
        sys.exit(f"실패: {' '.join(cmd)}\n{out.stderr.strip()}")
    return out.stdout.strip()


def git(*args, cwd, check=True):
    return run(["git", "-C", cwd, *args], check=check)


def plan(work, lead_name, root, cfg):
    if not cfg.is_id(work):
        sys.exit(f"작업 ID는 {cfg.id_shape} 꼴이다: {work}")
    hits = glob.glob(os.path.join(root, cfg.rel("quests"), f"{work}-*", "requirements.md"))
    if len(hits) != 1:
        sys.exit(f"{work}의 요구사항 {cfg.rel('quests')}/{work}-*/requirements.md가 하나여야 한다: {hits}")
    folder = os.path.basename(os.path.dirname(hits[0]))
    _, _, slug = cfg.split_folder(folder)
    session_dir = os.path.join(cfg.records_dir(root), work)
    worktree = cfg.worktree_for(root, work, folder)
    return {
        "work": work,
        "folder": folder,
        "requirements": os.path.relpath(hits[0], root),
        "branch": cfg.work_branch(folder),
        "lead_top": root,
        "worktree": worktree,
        "session_dir": session_dir,
        "settings": os.path.join(session_dir, "settings.json"),
        "prompt_file": os.path.join(session_dir, "task.md"),
        "standing": os.path.join(session_dir, STANDING),
        "orders": os.path.join(worktree, ORDERS_DIR, ORDERS),
        "home": session_home(),
        "plugin_root": config.PLUGIN_ROOT,  # 작업 세션은 `claude --plugin-dir <이 자리>`로 뜬다(훅이 늘 걸리게)
        "block_git": list(rules.git().block_git),
        "block_git_args": list(rules.git().block_git_args),
        "title": cfg.title_for(work, slug),
        "lead_name": lead_name,
        "terminal": cfg.terminal,  # 띄운 터미널 — merge가 같은 것으로 닫는다
    }


def session_home():
    """작업 세션의 Claude 홈 — 여는 쪽 환경의 `CLAUDE_CONFIG_DIR`, 없으면 `~/.claude`(작업 세션은 여는 쪽 환경을 그대로 받는다)."""
    return os.path.realpath(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


def committed_problems(root, rel):
    """rel이 커밋돼 있고 커밋 안 한 변경이 없으면 []."""
    if git("ls-files", "--", rel, cwd=root) == "":
        return [f"커밋돼 있지 않다: {rel}"]
    if git("status", "--porcelain", "--", rel, cwd=root):
        return [f"커밋 안 한 변경이 있다: {rel}"]
    return []


def check_lead(p, cfg):
    problems = open_problems(p, cfg)
    root = p["lead_top"]
    branch = git("branch", "--show-current", cwd=root)
    if branch != cfg.integration:
        problems.append(f"리드 체크아웃이 {cfg.integration}가 아니다: {branch}")
    for rel in (p["requirements"], cfg.rel("quest_list")):
        problems += committed_problems(root, rel)
    problems += committed_problems(root, config.CONFIG_REL)
    try:
        with open(os.path.join(root, cfg.rel("quest_list")), encoding="utf-8") as f:
            if not re.search(rf"^\|\s*{re.escape(p['work'])}\s*\|", f.read(), re.M):
                problems.append(f"작업 목록에 {p['work']} 줄이 없다: {cfg.rel('quest_list')}")
    except OSError:
        problems.append(f"작업 목록을 읽지 못했다: {cfg.rel('quest_list')}")
    with open(os.path.join(root, p["requirements"]), encoding="utf-8") as f:
        text = f.read()
    head = text[:1000]
    if "결정 번호:" not in head or not re.search(r"흐름:\s*quest\b", head):
        problems.append(f"요구사항 머리에 '결정 번호:'와 '흐름: quest'이 없다: {p['requirements']}")
    problems += req_commit_problems(p, cfg)
    template = cfg.requirements_template(root)
    if not os.path.exists(template):
        problems.append(f"요구사항 틀이 없다: {template}")
    else:
        problems += [f"요구사항이 틀에 맞지 않는다: {x}" for x in requirements.requirements_problems(text, template)]
    if git("rev-parse", "--verify", "--quiet", p["branch"], cwd=root, check=False):
        problems.append(f"브랜치가 이미 있다: {p['branch']}")
    if os.path.exists(p["worktree"]):
        problems.append(f"워크트리 자리가 이미 있다: {p['worktree']}")
    if not os.path.exists(HOOKS_JSON):
        problems.append(f"훅 파일이 없다: {HOOKS_JSON}")
    if not p["lead_name"].strip():
        problems.append("--lead <리드 세션 이름>이 없다. 작업 세션이 SendMessage로 리드에게 보낼 이름이다.")
    problems += terminal.problems(cfg.terminal)
    problems += worktree_place_problems(p)
    return problems


def req_commit_problems(p, cfg):
    """여는 작업의 요구사항 커밋(흐름 규칙 리드 단계 `<ID> req:`, 묶음 제목도)이 통합 브랜치에 있어야 한다.
    제목 정규식은 단계 찾기(`commits.steps_of`)와 같은 `Flow.title_re`."""
    flow = rules.flow()
    title = flow.title_re(p["work"], flow.lead_steps, bundle=True)
    subjects = git("log", "--format=%s", cfg.integration, cwd=p["lead_top"], check=False).splitlines()
    if any(title.match(s) for s in subjects):
        return []
    shape = flow.title(p["work"], flow.lead_steps[0])
    return [f"`{shape} …` 커밋이 {cfg.integration}에 없다 — 요구사항은 그 제목으로 커밋한 뒤 연다"]


def worktree_place_problems(p):
    """작업 워크트리 자리가 리드 저장소 꼭대기 안(같은 자리 포함)이면 연다 — 리드 저장소 전체를 막는 deny(`Edit(<리드>/**)`)가
    워크트리까지 덮는다. 실제 경로(심볼릭 링크를 푼 것)로 견준다(아직 없는 자리는 있는 조상까지 풀어 붙인다)."""
    lead, wt = os.path.realpath(p["lead_top"]), os.path.realpath(p["worktree"])
    if wt == lead or wt.startswith(lead + os.sep):
        return [f"작업 워크트리 자리 {p['worktree']}가 리드 저장소 {p['lead_top']} 안이다 — 리드 저장소 전체를 못 고치게 하는 deny가 "
                "워크트리까지 덮어 작업 세션이 아무것도 고치지 못한다(자리는 고정 `{parent}/{repo}-{id_lower}` — 리드 저장소 자리를 본다)."]
    return []


def cleanup_hint(p):
    return (f"정리: 작업 세션이 떴으면 닫고, git -C {shlex.quote(p['lead_top'])} worktree remove --force {shlex.quote(p['worktree'])}"
            f" && git -C {shlex.quote(p['lead_top'])} branch -D {shlex.quote(p['branch'])}")


def launch_command(p, cfg):
    """작업 세션을 띄우는 셸 한 줄(워크트리에서 claude) — 모델은 설정 `session.model`, 권한은 늘 `--dangerously-skip-permissions`
    (세션 deny와 훅은 그대로 걸린다), 이 플러그인(훅)을 `--plugin-dir`로 늘 싣는다."""
    args = ["--model", cfg.model, config.PERMISSION_FLAG, "--plugin-dir", p["plugin_root"],
            "--name", p["title"], "--settings", p["settings"], f"{p['prompt_file']}를 읽고 그대로 따른다."]
    return f"cd {shlex.quote(p['worktree'])} && claude " + " ".join(shlex.quote(a) for a in args)
