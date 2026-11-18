"""끝 확인 항목: 요구사항 머리(`흐름: seam`·결정 번호 범위)와 틀(`templates/requirements.md`)의 칸·절.
부명령 `feed`가 열기 전에 `requirements_problems`로 같은 틀 확인을 한다."""
import os
import re

from seam.libs.text import filled, read, section

DECISION_RANGE = re.compile(r"결정 번호:\s*(\d{4})~(\d{4})")


def flow_problems(head):
    return [] if re.search(r"흐름:\s*seam\b", head) else ["requirements.md 머리에 '흐름: seam' 없음"]


def decision_problems(ctx, work, head):
    """결정 폴더(`<설정 seam.pieces의 부모>/decisions`)의 이 작업 결정 파일이 요구사항 머리의 결정 번호 범위 안인가."""
    m = DECISION_RANGE.search(head)
    if m is None:
        return ["requirements.md 머리에 '결정 번호: NNNN~NNNN' 없음"]
    lo, hi = int(m.group(1)), int(m.group(2))
    folder = ctx.cfg.path("decisions", ctx.root)
    out = []
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
        n = re.match(r"(\d{4})-", f)
        if n and f"작업: {work}" in read(os.path.join(folder, f))[:600] and not lo <= int(n.group(1)) <= hi:
            out.append(f"결정 {f}가 요구사항 범위 {m.group(1)}~{m.group(2)} 밖")
    return out


def template_fields(template):
    """(머리 칸 이름들, `## ` 절 제목들) — 요구사항 틀에서 읽는다."""
    text = read(template)
    head = text.partition("\n## ")[0]
    fields = []
    for line in head.splitlines():
        if line.startswith("- "):
            fields += [part.partition(":")[0].strip() for part in line[2:].split(" · ") if ":" in part]
    return fields, [ln.strip() for ln in text.splitlines() if ln.startswith("## ")]


def head_problems(text, fields):
    head = (text or "").partition("\n## ")[0]
    return [f"요구사항 머리에 틀의 칸 '{k}:'이 없다" for k in fields
            if not re.search(rf"(?:^- |· ){re.escape(k)}:", head, re.M)]


def requirements_problems(text, template):
    """요구사항이 틀의 머리 칸·절에 맞는지 — 부명령 `feed`가 열기 전에, 끝 확인이 머리 칸을 본다."""
    fields, titles = template_fields(template)
    return head_problems(text, fields) + [f"요구사항 `{t}`이 비었다" for t in titles if not filled(section(text or "", t))]
