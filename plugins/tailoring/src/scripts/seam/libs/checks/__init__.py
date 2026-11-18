"""끝 확인(`seam inspect`) — 항목마다 한 모듈, 이 파일은 차례대로 모은다.

기록은 `<설정 seam.pieces>/<ID>-<슬러그>/`의 파일 넷(requirements·plan·review·retro). 항목과 차례:

1. 기록 파일 넷과 비지 않은 절 — `records`
2. 요구사항 머리 `흐름: seam`·결정 번호 범위·틀의 칸 — `requirements`
3. review `## 반영` 대조표 — `review`
4. retro `## 끝 검증`의 `- <명령> → <결과>` 줄 — `records`
5. 작업 목록 줄(`끝`은 리드가 합칠 때) — `records`
6. plan `## 할 일` 꼴과 시험 커밋 순서 — `tdd`
7. 넘길 일 꼴 — `carry`
8. 바뀐 규칙 문장(설정 `seam.rule_docs`의 patterns가 있을 때만, 그때는 retro에 그 절도) — `rules`
9. 필수 단계 커밋 — `seam.libs.commits`
10. retro `## 닫을 장부 줄`과 장부 대조(상태 `요구사항 <이 작업>`인 줄마다 한 줄·꼴·근거), 작업 범위에서 장부를 고치지 않음 — `carry`
11. 장부·작업 번호 확인 — `seam.libs.ledger`

문제 문장과 차례가 출력이다. 항목을 옮기거나 더할 때 차례를 바꾸지 않는다.
"""
import os

from seam.libs import commits, ledger
from seam.libs.checks import carry, records, requirements, review, rules, tdd
from seam.libs.text import read


def end_problems(ctx, work):
    folder = ctx.piece_dir(work)
    if folder is None:
        return [f"{ctx.cfg.rel('pieces')}/{work}-*/ 없음"]
    texts, out = records.read_records(folder, ctx.cfg)
    head = texts.get("requirements.md", "")[:1000]
    if "requirements.md" in texts:
        out += requirements.flow_problems(head)
        out += requirements.decision_problems(ctx, work, head)
        out += requirements.head_problems(texts["requirements.md"], requirements.template_fields(ctx.requirements_template())[0])
    if "review.md" in texts:
        out += review.review_problems(ctx.cfg, texts["review.md"], has_carry=bool(carry.carry_items(texts.get("retro.md", ""))))
    if "retro.md" in texts:
        out += records.verify_problems(texts["retro.md"])
    status = records.readme_status(ctx, work)
    out += records.piece_list_problems(ctx, work, status)
    if "plan.md" in texts:
        out += tdd.todo_shape_problems(texts["plan.md"]) + tdd.tdd_problems(ctx, work, texts["plan.md"])
    if "retro.md" in texts:
        out += carry.carry_problems(ctx.cfg, texts["retro.md"], (status or "").startswith("끝"))
        if ctx.cfg.rule_docs.on:
            out += rules.rule_change_check(ctx, texts["retro.md"], work)[0]
    gone = commits.missing(commits.steps_of(ctx, work))
    if gone:
        out.append("빠진 단계: " + ", ".join(gone) + f" — 커밋 제목 '{work} <단계>: …'(빈 커밋으로 채울 수 있음)")
    out += carry.close_problems(ctx, work, texts.get("retro.md", "")) if "retro.md" in texts else []
    out += carry.ledger_touched_problems(ctx, work)
    out += [f"check_carryover: {x}" for x in ledger.check(ctx.root, ctx.cfg)]
    return out


def end_warnings(ctx, work):
    """막지 않는 알림. 끝 확인 결과는 바꾸지 않는다."""
    if not ctx.cfg.rule_docs.on:
        return []
    folder = ctx.piece_dir(work)
    path = os.path.join(folder, "retro.md") if folder else None
    if not path or not os.path.exists(path):
        return []
    return rules.rule_change_check(ctx, read(path), work)[1]
