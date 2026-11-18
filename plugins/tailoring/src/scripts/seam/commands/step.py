"""부명령 `step` — 작업 세션이 단계에 들어갈 때 부른다. 작업 워크트리 안에서 부른다.

  <seam> step <단계>   # 들어감 0(그 단계 안내를 찍는다), 앞 단계 커밋 없음 1, 잘못 부름·작업 세션 밖·설정·규칙 오류 2

단계는 흐름 규칙(`src/rules/flow.json`)에서 작업 세션이 찍는 단계(`plan`·`plan-review`·`test`·`run`·`review`·`fix`·`done`). 리드 몫(`req`는
리드가 커밋, `merge`는 부명령 `join`)은 대상이 아니다. 차례: 작업 세션 가르기(`seam/libs/session.py`) → 규칙 읽기 → 단계 사슬 확인
(`seam/libs/commits.py`의 `chain_problem` — 커밋 때 확인(guard)·끝 확인 차례와 같은 판정, 앞 단계로 되돌아가기는 된다) →
세션 기록 자리의 `steps.json`에 지금 단계와 시작한 단계 목록(guard가 커밋 때 읽는다) → 단계 안내(`src/skills/seam/steps/<단계>.md`)와
모든 단계 안내(`steps/common.md`)를 플러그인 자리 `${CLAUDE_PLUGIN_ROOT}`와 이름 자리표(`<ID>`·`<작업 폴더>`·`<리드>`·`<리뷰어 모델>` 등)를 채워 찍는다.
"""
import os
import re

from seam.libs import commits, config, rules, session
from seam.libs.steplog import STEPS_FILE, read_steps, record_start  # noqa: F401  단계 기록(guard도 읽는다)
from seam.libs.context import GitError

GUIDES = os.path.join(config.PLUGIN_ROOT, "src", "skills", "seam", "steps")  # 단계별 안내 `<단계>.md`
COMMON = os.path.join(GUIDES, "common.md")  # 모든 단계에 함께 찍는 안내(결정하는 법·결정 요청·막힘·커밋 꼴)


def guide_path(step):
    return os.path.join(GUIDES, f"{step}.md")


def fill(text, ctx, work, record):
    """안내 글의 자리 — 플러그인 자리와 이 작업의 이름들."""
    folder = ctx.piece_dir(work)
    values = {
        "${CLAUDE_PLUGIN_ROOT}": config.PLUGIN_ROOT,
        "<ID>": work,
        "<기록 폴더>": ctx.cfg.rel("pieces"),
        "<작업 폴더>": os.path.relpath(folder, ctx.root) if folder else f"{ctx.cfg.rel('pieces')}/{work}-<슬러그>",
        "<리드>": ctx.cfg.lead,
        "<리드 세션 이름>": record.get("session_name") or record.get("lead_name") or ctx.cfg.lead,
        "<통합 브랜치>": ctx.cfg.integration,
        "<안내 문서>": "·".join(f"`{d}`" for d in ctx.cfg.rel("guide_docs")) or "프로젝트 안내 문서",
        "<결정 폴더>": ctx.cfg.rel("decisions"),
        "<장부>": ctx.cfg.rel("carryover"),
        "<작업 목록>": ctx.cfg.rel("piece_list"),
        "<리뷰어 모델>": ctx.cfg.model,  # 리뷰어(하위 에이전트) 모델 = 작업 세션과 같은 모델(설정 session.model)
    }
    return re.sub("|".join(re.escape(k) for k in values), lambda m: values[m.group(0)], text)


def main(argv):
    flow = None
    try:
        flow = rules.flow()
        rules.load_all()
        found = session.work_session(os.getcwd())
    except (config.ConfigError, rules.RuleError, GitError, ValueError, OSError) as e:
        print(f"seam step: {e}")
        return 2
    own = flow.hand_steps["작업 세션"]
    if len(argv) != 1:
        print(f"쓰는 법: python3 {config.ENTRY} step <{'|'.join(own)}>")
        return 2
    step = argv[0]
    if step not in flow.names:
        print(f"seam step: 모르는 단계 {step!r} — {'·'.join(own)} 가운데 하나")
        return 2
    if step not in own:
        who = "부명령 `join`이 남긴다" if step == flow.merge_step else f"{flow.step(step)['by']}가 커밋한다(작업 세션 열기 전)"
        print(f"seam step: {step}은 리드 몫이다 — {who}. 작업 세션 단계: {'·'.join(own)}")
        return 2
    if found is None:
        print("seam step: 작업 세션(작업 브랜치 + 세션 기록) 안에서 부른다 — 작업 워크트리에서")
        return 2
    ctx, work, record = found
    try:
        problem = commits.chain_problem(ctx, work, step)
    except GitError as e:
        print(f"seam step: {e}")
        return 2
    if problem:
        prev = flow.prerequisite(step)
        print(f"seam step {step}: {problem}. 먼저 {prev} 단계를 마치고 `{flow.title(work, prev)} …`로 커밋한다"
              f"(`python3 {config.ENTRY} step {prev}`).")
        return 1
    path = guide_path(step)
    try:
        with open(path, encoding="utf-8") as f:
            guide = f.read()
        with open(COMMON, encoding="utf-8") as f:
            common = f.read()
        record_start(record["session_dir"], step)
    except (OSError, ValueError) as e:
        print(f"seam step: {e}")
        return 2
    print(f"seam step {step} — {work} {flow.step(step)['stage']}에 들어간다(안내: {path})\n")
    print(fill(guide, ctx, work, record).rstrip() + "\n")
    print(fill(common, ctx, work, record).rstrip())
    return 0
