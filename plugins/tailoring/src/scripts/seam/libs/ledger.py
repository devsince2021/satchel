"""넘길 일 장부·작업 번호 확인 — 부명령 `carryover`(`seam/commands/carryover.py`)와 끝 확인(`seam inspect`)이 같이 쓴다.

자리는 설정(`.studio/tailoring.json`)의 `seam.pieces`(기록 폴더)와 거기서 셈한 `<기록 폴더>/README.md`(작업 목록)·
`<기록 폴더>/carryover.md`(장부)다. 아래 `<ID>`는 작업 ID(`P-NNN`), `<C>`는 장부 ID(`C-NNN`)다(둘 다 고정 — `config.py`).
아는 번호는 작업 목록 `## 작업 목록` 줄과 `<기록 폴더>/<ID>-<슬러그>/requirements.md`다(옛 작업은 목록 줄만 남아도 된다).
① 회고(`<기록 폴더>/*/retro.md`)마다 `## 넘길 일` 절과 항목(`- `·`* `·`1. `, 들여 쓴 하위 항목 포함)이 하나 이상 있고, 항목마다 장부에 있는
  `[<C>-NNN]`이 있다("없음" 항목은 빼고). 목록 상태가 `끝`이 아닌 동안은 번호 없는 항목을 받는다 — 리드가 합칠 때(`seam join`)
  번호를 매기고 목록을 `끝`으로 바꾼다
② 작업 목록·장부·`<기록 폴더>/*/*.md`에 나오는 작업 ID(앞뒤가 영숫자 아님 — 뒤에 한글 조사가 붙어도 센다)가 아는 번호다
③ 작업 목록과 그 `## 작업 목록` 절이 있고, 기록 폴더마다 `requirements.md`가 있고 한 번호는 폴더 하나이며, 폴더 번호마다 목록 줄이 있고
  번호에 빈칸이 없다
④ 장부 상태 `요구사항 <ID>`의 번호가 아는 번호다
⑤ 목록 상태가 `끝`으로 시작하는 작업은 `retro.md`가 있다(자세한 끝은 `seam inspect`)
⑥ 장부 상태 `넘김`은 근거 칸에 보낸 증거(`msg <16진 8자+>` 또는 날짜+시각과 받는 쪽 주소 — 고정 `SendMessage`)가 있다
⑦ 장부 `| <C>-`로 시작하는 줄은 칸이 6개이고 상태가 정해진 낱말로 시작한다

`check(root, cfg)`가 어긴 까닭을 한 줄씩 돌려준다.
"""

import re
from pathlib import Path

from seam.libs import config
from seam.libs.text import cells_of

SENT_MSG = re.compile(r"\bmsg [0-9a-f]{8,}\b")
SENT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d")
ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")  # 목록 항목 `- `·`* `·`1. `
CARRY = "## 넘길 일"
LIST_TITLE = "## 작업 목록"


def section(text, title):
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == title
            continue
        if inside:
            out.append(line)
    return out


class Shapes:
    """설정에서 나온 꼴."""

    def __init__(self, cfg):
        self.cfg = cfg
        idp = re.escape(cfg.prefix)
        self.id = re.compile(rf"(?<![A-Za-z0-9]){idp}-(\d{{{cfg.digits}}})(?![0-9])")  # \b는 한글을 글자로 세어 조사 붙은 ID를 놓친다
        self.state_word = re.compile(rf"(열림|넘김|끝|버림|요구사항 {cfg.id_pattern})")
        self.tag = re.compile(rf"\[({cfg.carry_pattern})\]")
        self.row_head = f"| {cfg.carry_prefix}-"
        addrs = "|".join(f"(?:{a})" for a in cfg.sent_addresses) or r"(?!)"
        self.sent_addr = re.compile(rf"(?<![\w/.-])(?:{addrs})(?![\w/])")

    def fmt(self, n):
        return f"{self.cfg.prefix}-{n}"


def readme_rows(readme, sh):
    """작업 목록 `## 작업 목록`의 {번호: 상태}."""
    rows = {}
    if readme.exists():
        head = re.compile(rf"\|\s*{re.escape(sh.cfg.prefix)}-(\d{{{sh.cfg.digits}}})\s*\|")
        for line in section(readme.read_text(encoding="utf-8"), LIST_TITLE):
            m = head.match(line)
            cells = cells_of(line) if m else []
            if m and len(cells) >= 3:
                rows[m.group(1)] = cells[2]
    return rows


def ledger_rows(ledger, problems, sh):
    rows = {}
    text = ledger.read_text(encoding="utf-8") if ledger.exists() else ""
    for line in text.splitlines():
        if not line.lstrip().startswith(sh.row_head):
            continue
        cells = cells_of(line)
        if not re.fullmatch(sh.cfg.carry_pattern, cells[0]):
            problems.append(f"{cells[0]}: ID 꼴이 아님")
            continue
        if cells[0] in rows:
            problems.append(f"{cells[0]}: 중복")
        if len(cells) != 6:
            problems.append(f"{cells[0]}: 장부 줄 꼴이 깨짐(칸 {len(cells)}개)")
        elif not sh.state_word.match(cells[4]):
            problems.append(f"{cells[0]}: 상태 낱말이 아님")
        rows[cells[0]] = cells
    if not ledger.exists():
        problems.append(f"{ledger.name}가 없다")
    return rows


def retro_problems(name, text, rows, untagged_ok, sh):
    if not any(line.strip() == CARRY for line in text.splitlines()):
        return [f"{name}: '{CARRY}' 절이 없다(넘길 것이 없으면 '- 없음')"]
    out = []
    items = [m.group(1) for line in section(text, CARRY) if (m := ITEM.match(line))]
    if not items:
        out.append(f"{name}: '{CARRY}'에 항목이 없다(넘길 것이 없으면 '- 없음')")
    for item in items:
        if item.strip().startswith("없음"):
            continue
        tags = sh.tag.findall(item)
        if not tags and not untagged_ok:
            out.append(f"{name}: 넘길 일 항목에 [{sh.cfg.carry_shape}]이 없다: {item[:60]}")
        out += [f"{name}: {t}가 장부에 없다" for t in tags if t not in rows]
    return out


def check(root, cfg=None):
    """root(저장소 뿌리)의 기록·목록·장부를 본다. cfg가 없으면 root의 설정."""
    root = Path(root)
    cfg = cfg or config.load(str(root))
    sh = Shapes(cfg)
    pieces_rel = cfg.rel("pieces").rstrip("/")
    pieces_root = root / pieces_rel
    problems = []
    pieces, folders = {}, {}
    for folder in sorted(p for p in pieces_root.glob(f"{cfg.prefix}-*") if p.is_dir()):
        m = sh.id.match(folder.name)
        if not m:
            continue
        folders.setdefault(m.group(1), []).append(folder.name)
        if (folder / "requirements.md").exists():
            pieces.setdefault(m.group(1), folder / "requirements.md")
        else:
            problems.append(f"{pieces_rel}/{folder.name}: requirements.md가 없다")
    for n, names in sorted(folders.items()):
        if len(names) > 1:  # 한 번호는 기록 폴더 하나 — Context.piece_dir와 같은 폴더(앞의 것)를 보게
            problems.append(f"{sh.fmt(n)}: {pieces_rel} 폴더가 둘 이상이다({', '.join(names)})")
    readme = root / cfg.rel("piece_list")
    statuses = readme_rows(readme, sh)
    # 작업 목록이 옛 번호의 근거다 — 읽지 못하면 조용히 통과하지 않는다.
    list_name = cfg.rel("piece_list")
    if not readme.exists():
        problems.append(f"{list_name}가 없다")
    elif not any(line.strip() == LIST_TITLE for line in readme.read_text(encoding="utf-8").splitlines()):
        problems.append(f"{list_name}에 '{LIST_TITLE}' 절이 없다")
    known = set(pieces) | set(statuses)
    ledger = root / cfg.rel("carryover")
    rows = ledger_rows(ledger, problems, sh)

    for n, req in pieces.items():
        retro = req.parent / "retro.md"
        if retro.exists():
            # 작업 세션은 넘길 일을 번호 없이 적고, 리드가 합칠 때(목록 `끝`) 번호를 매긴다.
            untagged_ok = not statuses.get(n, "").startswith("끝")
            problems += retro_problems(f"{req.parent.name}/{retro.name}", retro.read_text(encoding="utf-8"), rows, untagged_ok, sh)

    docs = [(d.name, d) for d in (readme, ledger)]
    docs += [(f"{d.parent.name}/{d.name}", d) for d in sorted(pieces_root.glob(f"{cfg.prefix}-*/*.md"))]
    for name, doc in docs:
        if doc.exists():
            problems += [f"{name}: {sh.fmt(n)}가 작업 목록에도 {pieces_rel}/에도 없다"
                         for n in sorted(set(sh.id.findall(doc.read_text(encoding="utf-8")))) if n not in known]

    for n in sorted(pieces):
        if n not in statuses:
            problems.append(f"작업 목록에 {sh.fmt(n)} 줄이 없다")
        elif statuses[n].startswith("끝") and not (pieces[n].parent / "retro.md").exists():
            problems.append(f"{sh.fmt(n)}: 끝인데 {pieces_rel}/{pieces[n].parent.name}/retro.md가 없다")
    if known:
        for k in range(1, max(int(n) for n in known) + 1):
            if f"{k:0{cfg.digits}d}" not in known:
                problems.append(f"{cfg.fmt_id(k)}이 비었다(번호는 작업 목록 줄이나 {pieces_rel}/ 요구사항으로만 생긴다)")

    req_state = re.compile(rf"요구사항 {re.escape(cfg.prefix)}-(\d{{{cfg.digits}}})")
    for cid, cells in rows.items():
        m = req_state.match(cells[4]) if len(cells) > 4 else None
        if m and m.group(1) not in known:
            problems.append(f"{cid}: 상태의 {sh.fmt(m.group(1))}가 작업 목록에도 {pieces_rel}/에도 없다")
        if len(cells) == 6 and cells[4].startswith("넘김"):
            proof = cells[5]
            if not (SENT_MSG.search(proof) or (SENT_TIME.search(proof) and sh.sent_addr.search(proof))):
                problems.append(f"{cid}: 넘김인데 보낸 근거 없음")
    return problems
