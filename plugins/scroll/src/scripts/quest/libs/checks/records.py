"""끝 확인 항목: 기록 파일 넷과 절, retro `## 끝 검증` 줄, 작업 목록 줄."""
import os
import re

from quest.libs.text import cells_of, content_lines, filled, read, section

SECTIONS = {
    "requirements.md": ("## 문제", "## 요구", "## 범위", "## 수용 기준"),
    "plan.md": ("## 잰 코드 사실", "## 결정", "## 할 일", "## 코드 전 검토", "## 구현하며 바뀐 것"),
    "review.md": ("## 동작", "## 문서·규칙", "## 반영"),
    "retro.md": ("## 끝 검증", "## 어긋난 것", "## 닫을 장부 줄", "## 넘길 일"),
}
RULE_SECTION = "## 바뀐 규칙 문장"  # 설정 `quest.rule_docs`의 patterns가 있을 때만 retro에 있어야 하는 절(`## 어긋난 것` 다음)


def sections(cfg):
    """파일마다 비지 않아야 할 절. "바뀐 규칙 문장" 확인이 켜졌으면 retro에 그 절을 더한다(원래 차례대로)."""
    if not cfg.rule_docs.on:
        return SECTIONS
    out = dict(SECTIONS)
    out["retro.md"] = ("## 끝 검증", "## 어긋난 것", RULE_SECTION, "## 닫을 장부 줄", "## 넘길 일")
    return out
VERIFY_LINE = re.compile(r"^- .+→.+", re.M)


def read_records(folder, cfg):
    """({파일 이름: 글}, 문제) — 파일 넷마다 없음·비지 않은 절."""
    texts, out = {}, []
    for name, titles in sections(cfg).items():
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            out.append(f"{name} 없음")
            continue
        texts[name] = read(path)
        out += [f"{name} `{t}`이 비었다" for t in titles if not filled(section(texts[name], t))]
    return texts, out


def has_verify_line(retro_text):
    """retro `## 끝 검증`에 `- <명령> → <결과>` 줄이 있나."""
    return bool(VERIFY_LINE.search("\n".join(content_lines(section(retro_text, "## 끝 검증")))))


def verify_problems(retro_text):
    return [] if has_verify_line(retro_text) else ["retro.md `## 끝 검증`에 '- <명령> → <결과>' 줄이 없다"]


def readme_status(ctx, work):
    """작업 목록(`<설정 quest.quests>/README.md`) `## 작업 목록`의 이 작업 상태 칸. 줄이 없으면 None."""
    path = ctx.cfg.path("quest_list", ctx.root)
    text = read(path) if os.path.exists(path) else ""
    for line in (section(text, "## 작업 목록") or "").splitlines():
        c = cells_of(line) if line.startswith("|") else []
        if c and c[0] == work:
            return c[2] if len(c) > 2 else ""
    return None


def quest_list_problems(ctx, work, status):
    return [f"작업 목록({ctx.cfg.rel('quest_list')})에 {work} 줄이 없다"] if status is None else []
