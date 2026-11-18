"""합치기 기록 — 기록 커밋 `<ID> merge: README 끝·넘길 일 <C>-…·장부 닫음 <C>-…`의 글(작업 목록 `끝`, 장부 번호, 회고
`## 닫을 장부 줄`대로 장부 줄 닫기 — 장부는 리드만 쓴다), 회고 `## 바뀐 규칙 문장` 읽기,
세션 기록의 경고, 세션 닫기 차례를 사람이 읽는 줄로. 부명령 `join`이 쓴다.
"""
import glob
import os
import re

from libs import git as gitlib
from seam.libs import rules as flow_rules  # 흐름 규칙(`src/rules/flow.json`) — 아래 `rules`는 끝 확인 항목 checks/rules(바뀐 규칙 문장)
from seam.libs import terminals as terminal
from seam.libs.checks import carry, rules  # 넘길 일 꼴·바뀐 규칙 문장 읽기
from seam.libs.text import cells_of, read, section


def git(cwd, *args):
    return gitlib.run(cwd, *args).strip()


def record_warnings(s):
    if not (s.get("session_name") or "").strip():
        return [f"경고: session.json의 session_name이 비었다(리드가 {s.get('work')} 시작 메시지의 from을 적지 않았다). 병합은 계속한다."]
    return []


def retro_path(worktree, work, cfg):
    hits = sorted(glob.glob(os.path.join(worktree, cfg.rel("pieces"), f"{work}-*", "retro.md")))
    return hits[0] if hits else None


def rule_change_lines(worktree, work, cfg):
    """회고 `## 바뀐 규칙 문장`의 줄 — 끝 확인(`inspect`)이 대조한 줄과 같게 읽는다. 회고나 절이 없으면 None."""
    path = retro_path(worktree, work, cfg)
    text = read(path) if path and os.path.exists(path) else ""
    if section(text, "## 바뀐 규칙 문장") is None:
        return None
    return rules.rule_items(text)


def rule_change_report(worktree, work, cfg):
    lines = rule_change_lines(worktree, work, cfg)
    if lines is None:
        return (f"바뀐 규칙 문장: 회고 `## 바뀐 규칙 문장`을 읽지 못했다({retro_path(worktree, work, cfg) or work + ' retro.md 없음'})"
                " — 리드가 회고를 직접 본다")
    return "\n".join(["바뀐 규칙 문장(보고에 옮긴다):", *lines]) if lines else "바뀐 규칙 문장: 없음"


def record_texts(work, last, readme, ledger, retro, cfg):
    """기록: 작업 목록 줄 상태 `끝(<last>, 로컬)`, 번호 없는 넘길 일마다 장부 다음 번호 —
    장부 마지막 줄 뒤에 `| <C>-NNN | <ID> | <받는 쪽> | <내용> | 열림 | - |`, 회고 항목 끝에 `[<C>-NNN]`.
    (readme, ledger, retro, [새 번호]). 이미 기록했으면 그대로 돌려준다."""
    cp = cfg.carry_prefix
    tag = re.compile(rf"\[{cfg.carry_pattern}\]")
    lines, inside = readme.split("\n"), False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            inside = line.strip() == "## 작업 목록"
        elif inside and re.match(rf"\|\s*{re.escape(work)}\s*\|", line):
            cells = cells_of(line)
            if len(cells) >= 3 and not cells[2].startswith("끝"):
                cells[2] = f"끝({last}, 로컬)"
                lines[i] = "| " + " | ".join(cells) + " |"
    readme = "\n".join(lines)
    nxt = max([0, *(int(n) for n in re.findall(rf"^\| {re.escape(cp)}-(\d{{3}}) \|", ledger, re.M))]) + 1
    rows, ids = [], []
    out, inside = retro.split("\n"), False
    for i, line in enumerate(out):
        if line.startswith("## "):
            inside = line.strip() == "## 넘길 일"
            continue
        item = line[2:].strip() if inside and line.startswith("- ") else None
        found = carry.CARRY_ITEM.match(item) if item and not item.startswith("없음") and not tag.search(item) else None
        if found:
            cid = f"{cp}-{nxt:03d}"
            nxt += 1
            content = re.sub(r"(?<!\\)\|", r"\\|", item[found.end(1) + 1:].strip())
            rows.append(f"| {cid} | {work} | {found.group(1).strip()} | {content} | 열림 | - |")
            out[i] = line.rstrip() + f" [{cid}]"
            ids.append(cid)
    if rows:
        ll = ledger.split("\n")
        # 마지막 장부 줄 뒤. 장부 줄이 아직 없으면 표 머리(마지막 `|` 줄) 뒤 — 빈 줄 뒤에 붙여 표가 끊기지 않게
        at = max((i for i, ln in enumerate(ll) if ln.lstrip().startswith(f"| {cp}-")),
                 default=max((i for i, ln in enumerate(ll) if ln.lstrip().startswith("|")), default=len(ll) - 1))
        ledger = "\n".join(ll[:at + 1] + rows + ll[at + 1:])
    return readme, ledger, "\n".join(out), ids


class RecordError(Exception):
    """기록 커밋을 쓸 수 없다(회고 `## 닫을 장부 줄`을 읽지 못함 등) — 합치기 전에 멈춘다."""


def close_rows(work, ledger, retro, cfg):
    """장부 줄 닫기: 회고 `## 닫을 장부 줄`(꼴은 `seam/libs/checks/carry.py`)의 줄마다 장부 그 줄의 상태·근거 칸을 고친다.
    → (장부 글, [닫은 장부 ID]). 이미 같은 상태·근거로 닫혔으면 그대로. 절이 없거나 꼴·근거가 틀리거나, 장부에 없는 줄·이 작업 줄이
    아닌 줄이 있거나, 고친 뒤 상태 `요구사항 <work>` 줄이 남으면 RecordError."""
    parsed = carry.close_entries(cfg, work, retro)
    if parsed is None:
        raise RecordError(f"회고에 `{carry.CLOSE}` 절이 없다 — 작업 세션이 줄마다 {carry.CLOSE_SHAPE}(없으면 `- 없음`)를 적는다")
    entries, problems = parsed
    if problems:
        raise RecordError("; ".join(problems))
    mine = f"요구사항 {work}"
    lines = ledger.split("\n")
    at = {cells_of(ln)[0]: i for i, ln in enumerate(lines) if ln.lstrip().startswith(f"| {cfg.carry_prefix}-")}
    closed = []
    for cid, state, proof in entries:
        if cid not in at:
            raise RecordError(f"`{carry.CLOSE}`의 {cid}가 장부에 없다")
        cells = cells_of(lines[at[cid]])
        if len(cells) != 6:
            raise RecordError(f"장부 {cid} 줄 꼴이 깨졌다(칸 {len(cells)}개)")
        if cells[4] == state and carry.unescape(cells[5]) == proof:
            continue  # 이미 옮겨 적었다
        if cells[4] != mine:
            raise RecordError(f"`{carry.CLOSE}`의 {cid}는 이 작업 줄(상태 `{mine}`)이 아니다 — 지금 상태 `{cells[4]}`")
        cells[4], cells[5] = state, re.sub(r"(?<!\\)\|", r"\\|", proof)
        lines[at[cid]] = "| " + " | ".join(cells) + " |"
        closed.append(cid)
    ledger = "\n".join(lines)
    left = [cid for cid, i in at.items() if (c := cells_of(lines[i])) and len(c) > 4 and c[4] == mine]
    if left:
        raise RecordError(f"장부에 상태 `{mine}`인 줄이 남는다: {', '.join(left)} — 회고 `{carry.CLOSE}`에 없다. 작업 세션에 돌려보낸다")
    return ledger, closed


def merge_title(work):
    """기록 커밋 제목 머리 — 흐름 규칙에서 `written_by: seam join`인 단계(`<ID> merge:`)."""
    flow = flow_rules.flow()
    return flow.title(work, flow.merge_step)


def write_record(s, work, cfg, body=()):
    """워크트리에 기록 커밋 `<ID> merge: README 끝·넘길 일 <C>-…·장부 닫음 <C>-…`(본문 줄 `body`) — 작업 목록 `끝`, 새 넘길 일 번호,
    회고 `## 닫을 장부 줄`대로 장부 줄 닫기(`close_rows`). 쓸 것이 없으면 아무것도 안 한다. 닫기를 못 하면 RecordError(아무것도 쓰지 않는다)."""
    wt = s["worktree"]
    paths = [cfg.path("piece_list", wt), cfg.path("carryover", wt), retro_path(wt, work, cfg)]
    olds = [read(p) if p and os.path.exists(p) else "" for p in paths]
    last = gitlib.short(git(wt, "rev-parse", "HEAD").strip())
    *news, ids = record_texts(work, last, *olds, cfg)
    closed = []
    if paths[2]:  # 회고가 없으면(끝 확인이 이미 막는 꼴) 작업 목록·번호처럼 건너뛴다. 회고가 있는데 절을 못 읽으면 멈춘다
        news[1], closed = close_rows(work, news[1], news[2], cfg)
    if news == olds:
        return None
    for path, old, new in zip(paths, olds, news):
        if path and new != old:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            git(wt, "add", path)
    title = (f"{merge_title(work)} README 끝" + (f"·넘길 일 {'·'.join(ids)}" if ids else "")
             + (f"·장부 닫음 {'·'.join(closed)}" if closed else ""))
    git(wt, "commit", "-q", "-m", title, *[x for line in body for x in ("-m", line)])
    return title


def close_lines(s, cfg):
    """세션 닫기 차례를 사람이 읽는 줄로 — 세션을 연 터미널(세션 기록 `terminal`)의 프리셋 또는 custom 틀."""
    plan = terminal.close_plan(s, cfg)
    if isinstance(plan, str):
        return [f"세션 닫기: {plan}"]
    return [f"세션 닫기: {shown}" for _, shown in plan]
