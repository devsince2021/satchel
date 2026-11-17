"""부명령 `rules-doc` — 문서의 흐름 규칙 생성 구역을 정본 `src/rules/flow.json`에서 다시 만든다. 어디서 불러도 같다(플러그인 파일만 본다).

  <quest> rules-doc           # 생성 구역을 다시 써 넣는다 — 0(고친 파일을 찍는다)
  <quest> rules-doc --check   # 쓰지 않고 견준다 — 같으면 0, 다르면 1(다른 파일을 찍는다)

차례: 인자 확인 → 구역 만들기·견주기(`quest/libs/docgen.py`) → 고친·다른 파일 찍기. 규칙 파일 오류·표지 없음·잘못 부름은 2.
"""
from quest.libs import config, docgen, rules


def main(argv):
    if argv not in ([], ["--check"]):
        print(f"쓰는 법: python3 {config.ENTRY} rules-doc [--check]")
        return 2
    check = argv == ["--check"]
    try:
        found = docgen.regenerate(write=not check)
    except (rules.RuleError, docgen.DocError) as e:
        print(f"rules-doc: {e}")
        return 2
    differ = [rel for rel, d in found if d]
    for rel in differ:
        print(f"rules-doc: {'다름' if check else '고침'}: {rel}")
    if not differ:
        print("rules-doc: 생성 구역이 flow.json과 같다")
    return 1 if check and differ else 0
