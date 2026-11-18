"""부명령 `carryover` — 넘길 일 장부와 작업 번호가 빠지지 않았는지 본다(확인 항목은 `seam/libs/ledger.py`).

  <seam> carryover [<저장소 뿌리>]   # 기본은 지금 자리가 든 git 작업본

차례: 저장소 뿌리 찾기 → 규칙 파일 읽기 → 장부 확인 → 까닭을 한 줄씩 찍기. 통과 0, 어기면 1, 부를 자리·설정·규칙 파일 오류 2.
"""
import os

from seam.libs import config, ledger, rules


def main(argv):
    root = argv[0] if argv else config.project_root(os.getcwd())
    if not root:
        print("check_carryover: git 작업본 안에서 부르거나 저장소 뿌리를 준다")
        return 2
    try:
        rules.load_all()  # 규칙 파일이 깨졌으면 판정 전에 멈춘다(다른 부명령과 같게)
        problems = ledger.check(root)
    except config.ConfigError as e:
        print(f"check_carryover: 설정 오류: {e}")
        return 2
    except rules.RuleError as e:
        print(f"check_carryover: 규칙 오류: {e}")
        return 2
    for p in problems:
        print(p)
    print(f"check_carryover: {'위반 ' + str(len(problems)) if problems else '통과'}")
    return 1 if problems else 0
