"""끝 확인 항목: retro `## 넘길 일` 꼴(한 줄 `- <받는 쪽>: <내용>`, 번호는 합칠 때)과
retro `## 닫을 장부 줄`(장부에 상태 `요구사항 <이 작업>`인 줄마다 한 줄 — 장부는 리드만 쓴다).

`## 닫을 장부 줄`의 꼴(합치기 기록 `quest/libs/record.py`의 `close_rows`도 이 읽기를 쓴다):
- 줄마다 `- <C-NNN>: <상태> — <근거>`. 상태는 `끝`(근거: 커밋·결정·시험)·`버림`(근거: 까닭)·`넘김`(근거: 보낸 증거 —
  `msg <16진 8자+>` 또는 날짜·시각과 받는 쪽 주소 `SendMessage`)·`열림`(근거: `<이 작업 ID> 넘김 — <까닭>`).
- 걸린 줄이 없으면 `- 없음`.
"""
import re

from libs import git as gitlib
from quest.libs import commits, ledger
from quest.libs import rules as flow_rules
from quest.libs.context import GitError
from quest.libs.text import COMMENT, cells_of, read, section

CARRY_ITEM = re.compile(r"^([^:`|\s][^:`|]{0,19}):\s+\S")  # `<받는 쪽>: <내용>` — 받는 쪽 1~20자
CARRY_LINE = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+(.*)$")
CLOSE = "## 닫을 장부 줄"
CLOSE_STATES = ("끝", "버림", "넘김", "열림")
CLOSE_SHAPE = "`- <C-NNN>: <끝|버림|넘김|열림> — <근거>`"
DASH = r"\s+[—–-]\s+"  # 상태와 근거 사이(`—` 권장, `–`·`-`도 받는다 — `TDD 예외 — `와 같게)


def unescape(cell):
    """장부 칸 글 — 표 안 `\\|`를 `|`로(회고 줄과 견줄 때)."""
    return cell.replace("\\|", "|")


def close_entries(cfg, work, retro_text):
    """retro `## 닫을 장부 줄` 읽기 → ([(장부 ID, 상태, 근거)], 문제). 절이 없으면 None."""
    body = section(retro_text or "", CLOSE)
    if body is None:
        return None
    line_re = re.compile(rf"^-\s+({cfg.carry_pattern}):\s*({'|'.join(CLOSE_STATES)}){DASH}(\S.*?)\s*$")
    sent_addr = ledger.Shapes(cfg).sent_addr
    entries, out, none, seen = [], [], False, set()
    for raw in COMMENT.sub("", body).splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(("- ", "* ")) and not re.match(r"\d+\.\s", line):
            continue  # 목록 밖 글은 설명으로 둔다
        if re.fullmatch(r"-\s+없음\.?", line):
            none = True
            continue
        m = line_re.match(line)
        if not m:
            out.append(f"retro.md `{CLOSE}` 줄 꼴이 아니다({CLOSE_SHAPE}): {line}")
            continue
        cid, state, proof = m.groups()
        if cid in seen:
            out.append(f"retro.md `{CLOSE}`에 {cid}가 두 번 있다")
            continue
        seen.add(cid)
        bad = proof_problem(work, state, proof, sent_addr)
        if bad:
            out.append(f"retro.md `{CLOSE}` {cid}: {bad}")
        entries.append((cid, state, proof))
    if none and entries:
        out.append(f"retro.md `{CLOSE}`에 `- 없음`과 줄이 함께 있다 — 줄이 있으면 `- 없음`을 지운다")
    return entries, out


def proof_problem(work, state, proof, sent_addr):
    """근거 칸 요건 — 지금 장부 줄 닫기 규칙 그대로. 맞으면 None."""
    if proof.strip() in ("-", "—", ""):
        return f"`{state}`의 근거가 비었다"
    if state == "넘김" and not (ledger.SENT_MSG.search(proof) or (ledger.SENT_TIME.search(proof) and sent_addr.search(proof))):
        return "넘김인데 보낸 근거 없음(`msg <16진 8자+>` 또는 날짜·시각과 받는 쪽 주소 `SendMessage`)"
    if state == "열림" and not re.match(rf"{re.escape(work)} 넘김{DASH}\S", proof):
        return f"열림의 근거는 `{work} 넘김 — <까닭>`이다"
    return None


def tag_re(cfg):
    """회고 넘길 일의 장부 번호 꼴 `[<C>-NNN]`."""
    return re.compile(rf"\[{cfg.carry_pattern}\]")


def carry_items(retro_text):
    """retro `## 넘길 일`의 `없음`이 아닌 항목 — review 반영 표의 `넘김`이 기대는 곳."""
    return [m.group(2) for ln in (section(retro_text, "## 넘길 일") or "").splitlines()
            if (m := CARRY_LINE.match(ln)) and not m.group(2).strip().startswith("없음")]


def carry_problems(cfg, retro_text, readme_done):
    """넘길 일 꼴: 한 줄 항목 `- <받는 쪽>: <내용>` 또는 `- 없음`. 번호(`[<C>-NNN]`)는 리드가 합칠 때(목록 `끝`)."""
    out = []
    tag = tag_re(cfg)
    for line in (section(retro_text, "## 넘길 일") or "").splitlines():
        m = CARRY_LINE.match(line)
        if not m:
            continue
        indent, item = m.group(1), m.group(2).strip()
        if indent:
            out.append(f"retro.md 넘길 일에 들여 쓴 하위 항목을 두지 않는다(한 항목 한 줄): {item}")
        elif not line.startswith("- "):  # 번호는 `- ` 항목에만 매긴다(합치기 기록 — record)
            out.append(f"retro.md 넘길 일은 `- ` 항목만 쓴다: {item}")
        elif item.startswith("없음"):
            continue
        elif not CARRY_ITEM.match(item):
            out.append(f"retro.md 넘길 일 꼴이 아니다(`- <받는 쪽>: <내용>` 또는 `- 없음`): {item}")
        elif tag.search(item) and not readme_done:
            out.append(f"retro.md 넘길 일 번호는 리드가 합칠 때 매긴다 — `[{cfg.carry_shape}]`을 지운다: {item}")
    return out


def ledger_cells(cfg, text):
    """장부 글의 {장부 ID: 칸 목록}(`| <C>-` 줄)."""
    return {c[0]: c for line in text.splitlines() if line.lstrip().startswith(f"| {cfg.carry_prefix}-") and (c := cells_of(line))}


def close_problems(ctx, work, retro_text):
    """retro `## 닫을 장부 줄`과 장부 대조: 장부에 상태 `요구사항 <work>`인 줄마다 한 줄이 있고, 절의 줄은 모두 이 작업의 줄이다.
    합친 뒤(기록 커밋이 장부를 고친 뒤)에는 같은 상태·근거로 닫힌 줄도 받는다. 절이 없으면 [](비었다는 records가 알린다)."""
    cfg = ctx.cfg
    parsed = close_entries(cfg, work, retro_text)
    if parsed is None:
        return []
    entries, out = parsed
    try:
        rows = ledger_cells(cfg, read(cfg.path("carryover", ctx.root)))
    except OSError:
        return out + [f"(장부를 읽지 못했다 — {cfg.rel('carryover')})"]
    mine = f"요구사항 {work}"
    named = set()
    for cid, state, proof in entries:
        named.add(cid)
        row = rows.get(cid)
        if row is None:
            out.append(f"retro.md `{CLOSE}`의 {cid}가 장부에 없다")
        elif len(row) != 6:
            continue  # 깨진 줄은 장부 확인(check_carryover)이 알린다
        elif row[4] != mine and not (row[4] == state and unescape(row[5]) == proof):
            out.append(f"retro.md `{CLOSE}`의 {cid}는 이 작업 줄(상태 `{mine}`)이 아니다 — 지금 상태 `{row[4]}`")
    left = [cid for cid, row in rows.items() if len(row) > 4 and row[4] == mine and cid not in named]
    if left:
        out.append(f"장부에 상태 `{mine}`인 줄이 retro.md `{CLOSE}`에 없다: {', '.join(left)} — 줄마다 {CLOSE_SHAPE}"
                   "(장부는 고치지 않는다 — 리드가 합칠 때 옮겨 적는다)")
    return out


def ledger_touched_problems(ctx, work):
    """작업 범위(`commits.work_base`..HEAD)에서 장부 파일이 바뀌었으면 막는다 — 장부는 리드가 합칠 때 고친다.
    합치기 기록 커밋(흐름 규칙 `written_by: quest merge` 단계 제목)이 HEAD면 그 커밋은 뺀다. 바뀐 뒤 되돌렸으면(차이 없음) 지나간다."""
    rel = ctx.cfg.rel("carryover")
    flow = flow_rules.flow()
    try:
        base = commits.work_base(ctx, work)
    except GitError:
        return []  # 작업 범위 기준(통합 브랜치)이 없다 — 다른 항목(바뀐 규칙 문장 등)이 알리고, 장부 대조는 이 항목 몫이 아니다
    head = ctx.git("log", "-1", "--format=%s", "HEAD").strip()
    end = "HEAD^" if flow.title_re(work, (flow.merge_step,)).match(head) else "HEAD"
    if not ctx.git("diff", "--name-only", base, end, "--", rel).strip():
        return []
    rows = ctx.git("log", "--format=%H %s", f"{base}..{end}", "--", rel).strip().splitlines()
    shas = [f"{gitlib.short(sha)} {subject}" for sha, _, subject in (r.partition(" ") for r in rows)]
    return [f"장부({rel})를 작업 범위에서 고쳤다({'; '.join(shas[:3])}) — 장부는 리드가 합칠 때 고친다. "
            f"장부 고침을 되돌리는 커밋을 만들고 닫을 줄은 retro.md `{CLOSE}`에 적는다"]
