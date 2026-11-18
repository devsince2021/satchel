"""문서 생성 구역 만들기 — 정본 `src/rules/flow.json`에서 SKILL.md·README의 흐름 규칙 구역 몸을 만들고 끼워 넣는다.
부명령 `rules-doc`(`seam/commands/rules_doc.py`)이 부른다. 생성 구역은 `<!-- rules:flow:begin -->` 줄과 `<!-- rules:flow:end -->`
줄 사이이고 구역 밖 글은 건드리지 않는다. 표지가 한 쌍이 아니면 DocError.
"""
import os

from seam.libs import rules

BEGIN = "<!-- rules:flow:begin -->"
END = "<!-- rules:flow:end -->"
NOTICE = "<!-- 이 구역은 부명령 `rules-doc`이 `src/rules/flow.json`에서 만든다. 손으로 고치지 않는다 — 고칠 것은 flow.json에 -->"
DOCS = ("src/skills/seam/SKILL.md", "README.md")  # 생성 구역이 있는 문서(플러그인 뿌리 기준)


class DocError(Exception):
    pass


def _code(text):
    return f"`{text}`"


def render(flow):
    """생성 구역 몸(표지 줄 사이) — 단계 표, 커밋 제목·할 일 번호, 차례 규칙, 리뷰어 기다림."""
    t = lambda step, more="": _code(f"{flow.title('<ID>', step)} {more}…")  # noqa: E731
    out = [NOTICE, "", "| 단계 | 커밋 제목 | 누가 | 필수 |", "| --- | --- | --- | --- |"]
    for s in flow.steps:
        who = s["by"] + (f"(부명령 `{s['written_by'].split()[-1]}`)" if s.get("written_by") else "")
        need = "필수" if s["required"] else "없어도 됨" + (f" — {s['note']}" if s.get("note") else "")
        out.append(f"| {s['stage']} | {t(s['name'], flow.todo_shape + ' ' if 'todo' in s else '')} | {who} | {need} |")
    names = "·".join(_code(n) for n in flow.names)
    bundle = flow.title_shape.replace("{id}", f"<ID>{flow.bundle_sep}<ID>").replace("{step}", "<단계>")
    out += ["",
            f"- 커밋 제목은 {_code(flow.title('<ID>', '<단계>') + ' …')}, 단계 차례는 표 차례({names}) — 부명령 `status`가 이 차례로 찍는다. "
            "필수 단계 커밋이 없으면 끝 확인(부명령 `inspect`)이 \"빠진 단계\"로 막는다. 커밋이 없는 단계는 `git commit --allow-empty`.",
            f"- 여러 작업을 한 커밋에 묶은 제목 {_code(bundle + ' …')}은 단계 찾기(`status`·빠진 단계·Stop 훅)에서 각 작업의 그 단계로 친다. "
            f"할 일 커밋과 차례 판정은 {_code(flow.title('<ID>', '<단계>'))} 꼴만 본다.",
            f"- 커밋하는 순간 PreToolUse 훅(부명령 `guard`)이 제목을 끝 확인과 같은 판정으로 본다 — 작업 세션은 이 작업 ID와 "
            f"작업 세션 단계({'·'.join(_code(n) for n in flow.hand_steps['작업 세션'])}), 리드 세션은 작업 ID로 시작하는 제목이 리드 단계"
            f"({'·'.join(_code(n) for n in flow.lead_steps)})인지와 요구사항 파일을 새로 더하는 커밋의 ID. "
            f"{_code(flow.merge_step)} 단계 커밋은 부명령 `join`만 남긴다. 제목은 `git commit -m`으로 쓴다(편집기·파일에서 읽는 꼴은 막는다)."]
    todo = flow.todo_steps
    must = [n for n in todo if flow.todo_required(n)]
    only = [n for n in flow.names if flow.tests_only(n)]
    line = (f"- 할 일 번호: {'·'.join(_code(n) for n in todo)} 커밋은 제목에 할 일 번호 {_code(flow.todo_shape)}"
            f"(여럿이면 {_code(flow.todo_many)})을 넣는다")
    if must:
        line += f" — {'·'.join(_code(n) for n in must)} 커밋에 없으면 막는다"
    line += "."
    if only:
        line += f" {'·'.join(_code(n) for n in only)} 커밋은 시험 파일만(하나 이상) 바꾼다(시험 파일은 규칙 `src/rules/tests.json`의 `patterns`)."
    out.append(line)
    o = flow.order
    first, then = o["todo_first"]["first"], o["todo_first"]["then"]
    clean, until = o["no_code_before"]["steps"], o["no_code_before"]["until"]
    fixed = o["exempt_fixed_at"]
    out += ["- 차례(끝 확인 `inspect`가 막는다):",
            f"  - 할 일 {_code(flow.todo_shape)}마다(`TDD 예외 — <까닭>` 할 일은 뺀다) {t(first, flow.todo_shape + ' ')} 커밋과 "
            f"{t(then, flow.todo_shape + ' ')} 커밋이 있고, 첫 {_code(first)} 커밋이 첫 {_code(then)} 커밋보다 앞(topo 차례).",
            "  - 단계마다 첫 커밋은 아래 \"단계 사슬\"의 앞 단계 첫 커밋 뒤(앞 단계 커밋이 없으면 \"빠진 단계\"가 막는다).",
            f"  - 첫 {_code(until)} 커밋 앞의 {'·'.join(_code(n) for n in clean)} 커밋은 구현 파일(시험 파일·기록 폴더·`.md` 밖)을 건드리지 않는다.",
            f"  - 첫 {_code(fixed['step'])} 커밋 때의 {_code(fixed['record'])}에 없던 `TDD 예외`는 "
            f"`## 구현하며 바뀐 것`에 `할 일 N`과 까닭이 있어야 한다."]
    work_steps = flow.hand_steps["작업 세션"]
    out += ["", "단계 사슬 — 작업 세션은 단계마다 시작 명령 `step <단계>`로 들어간다. 그 단계의 앞 단계 커밋이 있어야 들어가고, "
            "커밋하는 순간 PreToolUse 훅이 같은 사슬과 시작 명령으로 들어왔는지를 다시 본다. 앞 단계는 "
            + ("단계 차례에서 그 단계 앞으로 거슬러 처음 만나는 필수 단계(사이의 필수 아닌 단계는 없어도 된다)"
               if flow.chain_rule == "previous_required" else flow.chain_rule)
            + " — 단계에 `start_after`가 있으면 그 단계. 앞 단계로 되돌아가기는 된다. 리드 몫 단계는 시작 명령 대상이 아니다:", "",
            "| 단계 | 시작 명령 | 앞 단계 커밋 |", "| --- | --- | --- |"]
    for name in flow.names:
        prev = flow.prerequisite(name)
        start = _code(f"step {name}") if name in work_steps else ("부명령 `join`" if name == flow.merge_step else "리드가 커밋")
        why = " (`start_after`)" if "start_after" in flow.step(name) else ""
        out.append(f"| {flow.step(name)['stage']} | {start} | {_code(flow.title('<ID>', prev)) + why if prev else '—'} |")
    out.append("")
    before, after = flow.reviews["before_code"], flow.reviews["after_code"]
    reports = lambda r: "·".join(_code(p) for p in r["reports"])  # noqa: E731
    out += ["- 리뷰어 기다림(작업 세션 Stop 훅이 되돌린다, 보고는 작업 기록 폴더 기준):",
            f"  - 코드 전 검토 중 = {_code(before['after'])} 커밋 뒤 {_code(before['step'])} 커밋 전, 보고 {reports(before)}가 다 있기 전 — "
            f"할 일을 아직 안 썼거나 TDD 예외 아닌 할 일에 {t(first, flow.todo_shape + ' ')} 커밋이 없으면.",
            f"  - 코드 뒤 검토 중 = 할 일이 모두 `[x]`이고 {_code(after['after'])} 커밋 뒤 {_code(after['step'])} 커밋 전, "
            f"보고 {reports(after)}가 다 있기 전 — retro `## 끝 검증`에 `- <명령> → <결과>` 줄이 없으면."]
    out += ["", "합치기(부명령 `join`, 리드)의 단계 — 실패하면 출력에 멈춘 단계가 나온다. 합친 뒤 단계(푸시·알림)는 없다:", "",
            "| 단계 | 하는 일 | 값 |", "| --- | --- | --- |"]
    for m in flow.join:
        takes = "밖에서 받음 — 설정 " + "·".join(_code(t) for t in m["takes"]) if m["takes"] else "고정"
        out.append(f"| {m['stage']} | {m['does']} | {takes} |")
    return "\n".join(out)


def apply(text, body, where):
    """text의 생성 구역을 body로 바꾼 글. 표지가 한 쌍이 아니면 DocError."""
    lines = text.split("\n")
    begins = [i for i, ln in enumerate(lines) if ln.strip() == BEGIN]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == END]
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise DocError(f"{where}: 생성 구역 표지 `{BEGIN}`…`{END}`가 한 쌍이 아니다")
    return "\n".join(lines[:begins[0] + 1] + body.split("\n") + lines[ends[0]:])


def regenerate(root=None, write=True, flow=None):
    """[(문서 상대 경로, 다름)] — write면 다른 문서를 고쳐 쓴다."""
    root = root or rules.PLUGIN_ROOT
    body = render(flow or rules.flow())
    out = []
    for rel in DOCS:
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8") as f:
                old = f.read()
        except OSError as e:
            raise DocError(f"{rel}: 읽지 못했다: {e}") from e
        new = apply(old, body, rel)
        if new != old and write:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
        out.append((rel, new != old))
    return out
