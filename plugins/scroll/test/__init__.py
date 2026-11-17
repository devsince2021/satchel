"""scroll 플러그인 시험 — src/의 자리와 같은 꼴(src의 파일 하나 = 같은 자리 시험 하나 — 코드 src/scripts/는 test/scripts/, 꼴은 AGENTS.md "시험").

돌리기(저장소 뿌리에서): python3 -m unittest discover -s plugins/scroll/test -t plugins/scroll
이 묶음을 읽으면 플러그인 src/scripts/를 import 길 맨 앞에 둔다 — 시험 모듈이 공용 libs·quest·deliver를 이름으로 찾게(시험 폴더의
하위 묶음 test.scripts.libs·test.scripts.quest·test.scripts.deliver와 섞이지 않는다).
"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "scripts")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from test import helpers  # noqa: E402,F401  시험 설정·규칙 사본을 어느 시험 모듈보다 먼저 둔다
