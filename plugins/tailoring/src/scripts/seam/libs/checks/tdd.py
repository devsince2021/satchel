"""끝 확인 항목: plan `## 할 일` 꼴과 시험 커밋 순서 — 흐름 규칙(`src/rules/flow.json`)의 `order`를 본다:
`todo_first`(할 일마다 시험 커밋이 구현 커밋보다 앞, `TDD 예외 — <까닭>` 줄은 뺌), 단계 사슬 `chain`(단계마다 첫 커밋은 앞 단계 첫 커밋 뒤 —
`commits.chain_order_problems`, `seam step`·guard와 같은 `Flow.prerequisite`),
`no_code_before`(첫 시험 커밋 앞 계획 커밋에 구현 파일 없음), `exempt_fixed_at`(검토 뒤에 생긴 TDD 예외는 까닭).
시험 파일만 받는 단계(`tests_only`)는 시험 파일만(규칙 `src/rules/tests.json`의 `patterns`),
할 일 번호가 필수인 단계(`todo: 필수`)는 `#N`이 있어야 한다."""
import re

from libs import git as gitlib
from seam.libs import commits, rules
from seam.libs.text import COMMENT, section

TODO = re.compile(r"^- \[( |x)\] (\d+)\.(.*)$", re.M)
EXEMPT = re.compile(r"TDD 예외\s*[—–-]\s*\S")
LIST_LINE = re.compile(r"^(?:[-*]|\d+[.)])\s")


def todos(plan_text):
    """[(번호, 끝남, 줄 꼬리)] — plan `## 할 일`의 `- [ ] N.`·`- [x] N.` 줄."""
    return [(int(m.group(2)), m.group(1) == "x", m.group(3)) for m in TODO.finditer(section(plan_text or "", "## 할 일") or "")]


def todo_shape_problems(plan_text):
    """`## 할 일`의 목록 줄은 모두 `- [ ] N. …`·`- [x] N. …`이고 하나 이상 — 꼴이 어긋나 검사가 말없이 꺼지지 않게."""
    body = COMMENT.sub("", section(plan_text or "", "## 할 일") or "")
    out = [f"plan.md 할 일 줄 꼴이 아니다(`- [ ] N. …`·`- [x] N. …`): {ln.strip()}" for ln in body.splitlines()
           if LIST_LINE.match(ln) and not TODO.match(ln)]
    if not TODO.search(body):
        out.append("plan.md `## 할 일`에 `- [x] N. …` 할 일이 없다")
    return out


def is_record_file(cfg, path):
    """기록 폴더(설정 `seam.pieces`) 안 파일인가."""
    pieces = cfg.rel("pieces").strip("/")
    return ("/" + pieces + "/") in ("/" + path)


def tdd_problems(ctx, work, plan_text):
    """할 일마다 시험 커밋이 구현 커밋보다 앞, 시험 커밋은 시험 파일만(규칙 `src/rules/tests.json`의 `patterns`)."""
    cfg = ctx.cfg
    flow = rules.flow()
    judge = rules.tests()  # 시험 파일 판정(`src/rules/tests.json`)
    order = flow.order
    first, then = order["todo_first"]["first"], order["todo_first"]["then"]
    fixed = order["exempt_fixed_at"]
    found = commits.todo_commits(ctx, work)
    reviewed = commits.record_at(ctx, work, fixed["step"], fixed["record"])
    reviewed_exempt = {n for n, _, tail in todos(reviewed) if EXEMPT.search(tail)}
    changed = section(plan_text or "", "## 구현하며 바뀐 것") or ""
    out = []
    for n, done, tail in todos(plan_text):
        if not done:
            out.append(f"할 일 {n}가 끝나지 않았다(`- [ ]`)")
        if EXEMPT.search(tail):
            told = re.search(rf"할 일 {n}(?!\d)[^\n]*TDD 예외|TDD 예외[^\n]*할 일 {n}(?!\d)", changed)
            if reviewed is not None and n not in reviewed_exempt and not told:
                out.append(f"할 일 {n}: `TDD 예외`가 코드 전 검토({fixed['step']}) 뒤에 생겼다 — `## 구현하며 바뀐 것`에 `할 일 {n}`와 까닭을 적는다")
            continue
        tests = [i for i, (_, step, nums) in enumerate(found) if step == first and n in nums]
        runs = [i for i, (_, step, nums) in enumerate(found) if step == then and n in nums]
        if not tests:
            out.append(f"할 일 {n}: 시험 커밋 `{flow.title(work, first)} #{n} …`이 없다(TDD가 맞지 않으면 할 일 줄에 `TDD 예외 — <까닭>`)")
        if not runs:
            out.append(f"할 일 {n}: 구현 커밋 `{flow.title(work, then)} #{n} …`이 없다")
        if tests and runs and runs[0] < tests[0]:
            out.append(f"할 일 {n}: 구현 커밋이 시험 커밋보다 앞이다(TDD — 시험 `{flow.title(work, first)} #{n}` 먼저)")
    for sha, step, nums in found:
        if flow.tests_only(step):
            files = commits.touched(ctx, sha)
            bad = [f for f in files if not judge.is_test_file(f)]
            if bad:
                out.append(f"시험 커밋 {gitlib.short(sha)}이 시험 파일이 아닌 것을 건드린다: {', '.join(bad)}")
            if not any(judge.is_test_file(f) for f in files):
                out.append(f"시험 커밋 {gitlib.short(sha)}이 시험 파일을 바꾸지 않는다(빈 시험 커밋)")
        elif flow.todo_missing(step, nums):
            out.append(f"구현 커밋 {gitlib.short(sha)}에 할 일 번호 `{flow.todo_shape}`이 없다(`{flow.title(work, step)} {flow.todo_shape} …`)")
    # 단계 사슬 차례(흐름 규칙 `chain`): 단계마다 첫 커밋은 앞 단계 첫 커밋 뒤 — 예: 첫 구현 커밋은 첫 코드 전 검토 커밋 뒤,
    # 시험 커밋은 계획 뒤(검토를 기다리는 동안 써도 된다). 앞 단계 커밋이 없으면 쉰다("빠진 단계"가 막는다). `seam step`·guard와 같은 판정.
    out += commits.chain_order_problems(ctx, work)
    # 첫 시험 커밋 앞의 계획 커밋에 구현을 먼저 넣어 순서 검사를 비켜 가지 못하게(시험·기록 폴더·`.md` 밖 파일이 구현 파일) — order.no_code_before
    clean, until = order["no_code_before"]["steps"], order["no_code_before"]["until"]
    ordered = commits.todo_commits(ctx, work, (*clean, until))
    first_test = next((i for i, (_, step, _) in enumerate(ordered) if step == until), len(ordered))
    for sha, step, _ in ordered[:first_test]:
        code = [f for f in commits.touched(ctx, sha) if not judge.is_test_file(f) and not is_record_file(cfg, f) and not f.endswith(".md")]
        if code:
            out.append(f"시험 커밋보다 앞선 {step} 커밋 {gitlib.short(sha)}이 구현 파일을 건드린다: {', '.join(code)}")
    return out
