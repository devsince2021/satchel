"""끝 확인 항목: 바뀐 규칙 문장 — 작업 범위(`base`..HEAD)에서 규칙 문서(플러그인 설정 `quest.rule_docs`의 patterns)를 바꿨으면
retro `## 바뀐 규칙 문장`에 파일마다 옛 → 새 줄(규칙 문서를 안 바꿨는데 줄이 있으면 경고만).
patterns가 비거나 없으면(기본값) 이 항목은 통째로 건너뛴다 — 부르는 쪽(`checks`·부명령 `merge`)이 `cfg.rule_docs.on`을 본다."""
from quest.libs import commits
from quest.libs.context import GitError
from quest.libs.text import content_lines, section

RULE_SHAPE = "`- <규칙 파일>:<규칙 ID 또는 절> · <옛 문장> → <새 문장> · <까닭(결정 번호)>`"


def changed_rule_docs(ctx, work=None):
    """작업 범위(`work_base`..HEAD)에서 바뀐 규칙 문서(저장소 뿌리 기준 경로). 통합 브랜치가 없으면 GitError."""
    base = commits.work_base(ctx, work)
    # 비ASCII 경로를 따옴표로 싸지 않게(core.quotePath) `-z`로 받는다
    names = ctx.git("-c", "core.quotePath=false", "diff", "--name-only", "-z", "--no-renames", f"{base}..HEAD").split("\0")
    docs = ctx.cfg.rule_docs
    return sorted(p for p in names if p and docs.is_rule_doc(p))


def rule_items(retro_text):
    """`## 바뀐 규칙 문장`의 `- ` 줄(`- 없음` 뺌)."""
    return [ln for ln in content_lines(section(retro_text, "## 바뀐 규칙 문장")) if ln.startswith("- ") and not ln[2:].strip().startswith("없음")]


def rule_item_file(item):
    """줄의 파일 자리 — `- ` 뒤부터 첫 `:` 앞(앞뒤 공백·`` ` `` 뺌)."""
    return item[2:].partition(":")[0].strip().strip("`").strip()


def _strip_optional(path, cfg):
    head = cfg.rule_docs.optional_prefix
    return path[len(head):] if head and path.startswith(head) else path


def rule_change_check(ctx, retro_text, work=None):
    """(막힘, 경고)."""
    try:
        changed = changed_rule_docs(ctx, work)
    except GitError as e:
        return [f"규칙 문서 변경을 재지 못했다(작업 범위 기준 — {ctx.cfg.integration} 가지와 merge-base): {e}"], []
    items = rule_items(retro_text)
    files = {rule_item_file(it) for it in items}
    out = [f"retro.md 바뀐 규칙 문장 줄에 '옛 문장 → 새 문장'이 없다({RULE_SHAPE}): {it}" for it in items if "→" not in it]
    if changed and not items:
        out.append(f"규칙 문서를 바꿨는데 retro.md `## 바뀐 규칙 문장`이 비었거나 `- 없음`이다({RULE_SHAPE}): " + ", ".join(changed))
    elif changed:
        gone = [p for p in changed if p not in files and _strip_optional(p, ctx.cfg) not in files]
        if gone:
            out.append(f"retro.md `## 바뀐 규칙 문장`에 바뀐 규칙 문서가 빠졌다(파일마다 {RULE_SHAPE}): " + ", ".join(gone))
    warn = [] if changed or not items else [f"retro.md `## 바뀐 규칙 문장`에 줄이 있는데 작업 범위에서 바뀐 규칙 문서가 없다(규칙 문서 밖 문장이면 그대로 둔다): {len(items)}줄"]
    return out, warn
