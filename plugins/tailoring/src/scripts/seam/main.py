#!/usr/bin/env python3
"""seam 입구 — 부명령 하나로 흐름의 스크립트를 부른다. Python 3.9 이상, 표준 라이브러리만.

  <seam> feed <ID> --lead <리드 세션 이름> [--dry-run|--check-only] [--open <폴더>…]   # 작업 세션 열기(리드)
  <seam> step <단계>                  # 작업 세션이 단계에 들어갈 때 — 앞 단계 커밋 확인·단계 안내 찍기·지금 단계 기록(들어감 0, 앞 단계 없음 1, 잘못 부름 2)
  <seam> status <ID>                  # 커밋 제목으로 찾은 단계·첫 시각, 빠진 필수 단계
  <seam> inspect <ID>                     # 끝 확인 — 통과 0, 막힘 1, 잘못 부름·git 실패·설정 오류 2
  <seam> base <ID>                    # 작업 범위 기준 커밋(검토 범위 `<base>..HEAD`)
  <seam> join <ID> [--dry-run] [--keep] [--verified "<메모>"]   # 합치기(리드) — ① 확인 → ② deliver → ③ 치우기
  <seam> carryover [<저장소 뿌리>]     # 넘길 일 장부·작업 번호 확인 — 통과 0, 위반 1, 부를 자리 오류 2
  <seam> hold                         # 작업 세션이 멈추려 할 때 되돌리기 — Stop 훅(stdin에 훅 입력 JSON), 플러그인 src/hooks/hooks.json이 부른다
  <seam> guard                        # 작업 세션의 도구 호출 직전 막기(커밋 때 단계 확인 포함), 리드 세션의 피스 커밋 제목 — PreToolUse 훅(stdin에 훅 입력 JSON), 플러그인 src/hooks/hooks.json이 부른다
  <seam> rules-doc [--check]          # 문서의 흐름 규칙 생성 구역을 src/rules/flow.json에서 다시 만든다(--check는 견주기만, 다르면 1)

`<seam>` = `python3 <플러그인 뿌리>/src/scripts/seam/main.py`. 세션 PATH에 싣는 입구는 없다 — 사람과 세션은 스킬(/seam)로 쓰고, 스킬 문서는
`python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/seam/main.py" <부명령>`(Claude Code가 스킬 본문의 `${CLAUDE_PLUGIN_ROOT}`를 플러그인 뿌리로 바꿔 준다),
훅·시작 지시는 같은 꼴의 전체 경로로 부른다. 작업 저장소(또는 작업 워크트리) 안에서 부른다.
부명령 하나가 `src/scripts/seam/commands/`의 파일 하나다(`rules-doc` → `rules_doc.py`) — 자세한 것은 그 파일 머리글.
"""
import importlib
import os
import sys

# import 길의 첫 자리(이 파일이 든 src/scripts/seam)를 src/scripts/로 바꾼다 — 공용 libs·seam·deliver 묶음을 이름으로 찾고,
# 묶음 안 폴더 이름(libs·commands)이 공용 libs를 가리지 않게. 심볼릭 링크로 불러도 플러그인 안 자리를 찾게 실제 경로로 푼다
sys.path[0] = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

COMMANDS = ("feed", "step", "status", "inspect", "base", "join", "carryover", "hold", "guard", "rules-doc")
ENTRY = os.path.realpath(__file__)


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(f"쓰는 법: python3 {ENTRY} {'|'.join(COMMANDS)} …\n{__doc__}")
        return 2
    # 부명령 파일은 그때 읽는다 — 훅이 모든 세션에서 불리므로 쓰지 않는 파일을 읽지 않게
    command = importlib.import_module("seam.commands." + argv[0].replace("-", "_"))
    return command.main(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
