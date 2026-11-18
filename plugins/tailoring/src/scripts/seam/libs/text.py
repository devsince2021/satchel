"""기록 문서(마크다운) 읽기 — 절·채운 줄·표 칸. 끝 확인·Stop 훅·합치기·장부 확인이 같은 읽기를 쓴다."""
import re

COMMENT = re.compile(r"<!--.*?-->", re.S)
CODE_SPAN = re.compile(r"`[^`]*`")
PLACEHOLDER = re.compile(r"<[^<>`]+>")  # 틀 자리표 — 코드 조각(`…`) 밖에 남으면 채우지 않은 줄
TABLE_RULE = re.compile(r"^\|[\s|:-]*\|$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def section(text, title):
    """`## 제목` 절 몸(다음 `## ` 전까지). 없으면 None."""
    _, found, rest = text.partition(title + "\n")
    return rest.partition("\n## ")[0] if found else None


def content_lines(body):
    """빈 줄·주석·표 구분 줄과 틀 자리표(`<…>`, 코드 조각 밖)가 남은 줄을 뺀 줄."""
    lines = [ln.strip() for ln in COMMENT.sub("", body or "").splitlines()]
    return [ln for ln in lines if ln and not TABLE_RULE.match(ln) and not PLACEHOLDER.search(CODE_SPAN.sub("", ln))]


def filled(body):
    return bool(content_lines(body))


def cells_of(line):
    """표 줄을 칸으로 나눈다. 내용 안 `\\|`는 칸 구분이 아니다."""
    return [c.strip() for c in CELL_SPLIT.split(line.strip().strip("|"))]
