"""커밋 읽기 — 단계(커밋 제목 `<ID> <단계>:`), 할 일 커밋, 작업 범위 기준 커밋.

모든 함수는 문맥(`Context` — 저장소 뿌리·설정)을 첫 인자로 받는다. git 실패는 GitError.
단계 이름·차례·필수·제목 꼴·할 일 번호 꼴은 흐름 규칙(`quest/libs/rules.py` → `src/rules/flow.json`)에서 온다.
"""
import os
from datetime import datetime

from libs import git as gitlib
from quest.libs import rules
from quest.libs.context import GitError


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def touched(ctx, sha):
    return [f for f in ctx.git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).splitlines() if f]


# ---- 단계 ----

def steps_of(ctx, work):
    """[(단계, 첫 작성 시각)] — 흐름 규칙의 단계 차례. 제목이 `<ID> <단계>:`인 커밋.
    여러 작업을 한 커밋에 묶은 제목 `<ID>·<ID> <단계>:`도 각 작업의 그 단계로 받는다(흐름 규칙 `commit.bundle`)."""
    flow = rules.flow()
    title = flow.title_re(work, flow.names, bundle=True)
    first = {}
    for line in ctx.git("log", "--format=%H%x09%aI%x09%s", "HEAD").splitlines():
        sha, when, subject = line.split("\t", 2)
        m = title.match(subject)
        if m and (m.group(1) not in first or parse_ts(when) < parse_ts(first[m.group(1)])):
            first[m.group(1)] = when
    return [(s, first[s]) for s in flow.names if s in first]


def title_problem(work, subject, by):
    """커밋 제목 하나의 판정 — 막을 까닭 또는 None. 커밋 때 판정(PreToolUse 훅 guard — `quest/libs/gitcommit.py`)이 쓰고,
    단계 찾기(`steps_of` — 묶음 제목도 받음)·할 일 번호(`todo_commits`·끝 확인 checks/tdd의 `Flow.todo_missing`)와 같은 정규식·판정이다.
    by: 커밋하는 쪽(`작업 세션`·`리드`) — 그쪽이 손으로 찍는 단계(흐름 규칙 `by`, 합치기 기록 단계 뺌)만 받는다."""
    flow = rules.flow()
    own = flow.hand_steps[by]
    m = flow.title_re(work, flow.names, bundle=True, rest=True).match(subject)
    if not m:
        return (f"꼴이 `{flow.title(work, '<단계>')} …`이 아니다 — 이 작업 ID `{work}`와 단계 이름"
                f"({by}: {'·'.join(own)})")
    step, rest = m.group(1), m.group(2)
    if step == flow.merge_step:
        return f"`{step}` 단계 커밋은 부명령 merge가 남긴다 — 손으로 찍지 않는다"
    if step not in own:
        return f"`{step}`은 {flow.step(step)['by']}가 찍는 단계다 — {by}가 찍는 단계: {'·'.join(own)}"
    if flow.todo_missing(step, flow.todo_ref.findall(rest)):
        return f"`{step}` 커밋에 할 일 번호 `{flow.todo_shape}`이 없다(`{flow.title(work, step)} {flow.todo_shape} …`)"
    return None


def chain_problem(ctx, work, step):
    """단계 사슬(흐름 규칙 `chain` — `Flow.prerequisite`): `step`에 들어가거나 커밋하려면 앞 단계 커밋(`<ID> <앞 단계>:`, 묶음 제목도)이
    있어야 한다. 시작 명령(`quest step`)과 커밋 때 확인(guard)이 이 하나를 쓴다 — 막을 까닭 또는 None."""
    flow = rules.flow()
    prev = flow.prerequisite(step)
    if prev is None or prev in {s for s, _ in steps_of(ctx, work)}:
        return None
    return f"앞 단계 {prev} 커밋이 없다(`{flow.title(work, prev)} …`) — {step}은 {prev} 뒤에 온다"


def chain_order_problems(ctx, work):
    """끝 확인의 차례(사슬): 커밋이 있는 단계마다 첫 커밋이 앞 단계(`Flow.prerequisite`)의 첫 커밋보다 뒤(topo 차례, 묶음 제목도).
    앞 단계 커밋이 없으면 쉰다 — 필수면 "빠진 단계"가 막는다."""
    flow = rules.flow()
    title = flow.title_re(work, flow.names, bundle=True)
    first = {}
    for i, line in enumerate(ctx.git("log", "--topo-order", "--reverse", "--format=%H%x09%s", "HEAD").splitlines()):
        sha, _, subject = line.partition("\t")
        m = title.match(subject)
        if m and m.group(1) not in first:
            first[m.group(1)] = (i, sha)
    out = []
    for step, (i, sha) in first.items():
        prev = flow.prerequisite(step)
        if prev in first and i < first[prev][0]:
            out.append(f"{flow.step(step)['stage']} 커밋 {gitlib.short(sha)}이 {flow.step(prev)['stage']}(`{flow.title(work, prev)}`)보다 앞이다"
                       f" — 단계는 앞 단계 커밋 뒤(단계 사슬, `quest step`과 같은 판정)")
    return out


def missing(found):
    have = {s for s, _ in found}
    return [s for s in rules.flow().required if s not in have]


# ---- 할 일 커밋 ----

def todo_commits(ctx, work, steps=None):
    """[(해시, 단계, {할 일 번호})] — 제목 `<ID> <단계>: …`인 커밋, 오래된 것부터(topo 순서 — 리베이스가 시각을 바꿔도 남음).
    steps가 없으면 할 일 번호가 붙는 단계(흐름 규칙 `todo`)."""
    flow = rules.flow()
    title = flow.title_re(work, flow.todo_steps if steps is None else steps, rest=True)
    out = []
    for line in ctx.git("log", "--topo-order", "--reverse", "--format=%H%x09%s", "HEAD").splitlines():
        sha, _, subject = line.partition("\t")
        m = title.match(subject)
        if m:
            out.append((sha, m.group(1), {int(n) for n in flow.todo_ref.findall(m.group(2))}))
    return out


def record_at(ctx, work, step, name):
    """처음 `<ID> <step>:` 커밋 때의 기록 파일 `name`(예: plan.md) 글. 커밋·파일이 없으면 None."""
    folder = ctx.quest_dir(work)
    title = rules.flow().title_re(work, (step,))
    for line in ctx.git("log", "--topo-order", "--reverse", "--format=%H%x09%s", "HEAD").splitlines():
        sha, _, subject = line.partition("\t")
        if title.match(subject):
            rel = os.path.relpath(os.path.join(folder, name), ctx.root)
            try:
                return ctx.git("show", f"{sha}:./{rel}")
            except GitError:
                return None
    return None


# ---- 작업 범위 기준 커밋 ----

def _sha(ctx, ref):
    try:
        return ctx.git("rev-parse", "--verify", "-q", ref + "^{commit}").strip() or None
    except GitError:
        return None


def _is_ancestor(ctx, a, b):
    try:
        ctx.git("merge-base", "--is-ancestor", a, b)
        return True
    except GitError:
        return False


def requirements_parent(ctx, work):
    """이 작업 `requirements.md`를 처음 더한 커밋(요구사항 커밋)의 부모. 못 찾으면 None."""
    folder = ctx.quest_dir(work) if work else None
    if not folder:
        return None
    try:
        added = ctx.git("log", "--format=%H", "--diff-filter=A", "HEAD", "--", os.path.join(folder, "requirements.md")).split()
    except GitError:
        return None
    return _sha(ctx, added[-1] + "^") if added else None


def work_base(ctx, work=None):
    """작업 범위 기준 커밋: `merge-base HEAD <통합 브랜치>`·`merge-base HEAD <원격 통합 브랜치>`(있으면)·요구사항 커밋 부모
    가운데 다른 후보를 모두 품은 가장 가까운 것. 한 줄에 서지 않으면 `merge-base HEAD <통합 브랜치>`. 통합 브랜치가 없으면 GitError."""
    first = ctx.git("merge-base", "HEAD", ctx.cfg.integration).strip()
    found = [first]
    remote = ctx.cfg.remote_integration
    if remote and _sha(ctx, remote):
        try:
            found.append(ctx.git("merge-base", "HEAD", remote).strip())
        except GitError:
            pass
    found.append(requirements_parent(ctx, work))
    found = list(dict.fromkeys(c for c in found if c))
    for c in found:
        if all(o == c or _is_ancestor(ctx, o, c) for o in found):
            return c
    return first
