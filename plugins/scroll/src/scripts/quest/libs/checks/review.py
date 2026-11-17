"""끝 확인 항목: review `## 반영` 대조표 — 모든 지적이 `고침`·`기각 — <까닭>`·`넘김`이고
`고침`인 Critical·Important는 시험 칸이 있음."""
import re

from quest.libs.text import cells_of, section

COLUMNS = ("#", "지적", "출처", "등급", "한 일", "시험")
EMPTY_CELL = ("", "—", "-")
GRADES = ("Critical", "Important", "Minor")
OUTCOME = re.compile(r"^(고침|기각|넘김)")


def row_problems(cfg, n, grade, done, test, has_carry):
    """모든 지적은 `고침`·`기각 — <까닭>`·`넘김`(장부 번호 또는 retro 넘길 일 항목) 가운데 하나."""
    out = []
    if grade not in GRADES:
        out.append(f"review.md 반영 {n}: 등급 '{grade}'는 {'·'.join(GRADES)} 가운데 하나가 아니다(기각은 한 일 칸)")
    m = OUTCOME.match(done)
    if m is None:
        out.append(f"review.md 반영 {n}: 한 일 '{done}'은 `고침`·`기각`·`넘김` 가운데 하나로 시작해야 한다")
    elif m.group(1) == "기각" and not done[2:].strip(" —–-:·"):
        out.append(f"review.md 반영 {n}: `기각`인데 까닭이 없다(`기각 — <까닭>`)")
    elif m.group(1) == "넘김" and not re.search(cfg.carry_pattern, done) and not has_carry:
        out.append(f"review.md 반영 {n}: `넘김`인데 {cfg.carry_prefix} 번호도 retro `## 넘길 일` 항목도 없다")
    elif m.group(1) == "고침" and grade in ("Critical", "Important") and test in EMPTY_CELL:
        out.append(f"review.md 반영 {n}: {grade}인데 '시험' 칸이 비었다(시험으로 못 고정하면 '문서만 — <까닭>')")
    return out


def review_problems(cfg, text, has_carry=False):
    body = section(text, "## 반영") or ""
    rows = [ln for ln in body.splitlines() if ln.strip().startswith("|")]
    if not rows or cells_of(rows[0]) != list(COLUMNS):
        return ["review.md `## 반영`에 '| " + " | ".join(COLUMNS) + " |' 대조표가 없다"]
    out = []
    for row in rows[1:]:
        c = cells_of(row)
        if set("".join(c)) <= set("-: "):
            continue  # 구분 줄
        if len(c) != len(COLUMNS):
            out.append(f"review.md 반영 {c[0]}: 칸이 {len(c)}개")
            continue
        n, grade, done, test = c[0], c[3], c[4], c[5]
        out += row_problems(cfg, n, grade, done, test, has_carry)
    return out
