# ④ 코드 뒤 검토

## 할 일

1. 범위를 나눈 독립 리뷰어 둘을 한 메시지에서 동시에 띄운다(하위 에이전트, 둘 다 `model: <리뷰어 모델>` — 작업 세션과 같은 모델(설정 `session.model`)로 꼭 적는다, 읽기만): `${CLAUDE_PLUGIN_ROOT}/src/skills/seam/reviewers/behavior-reviewer.md`(동작 — 회귀 경계를 옛 코드와 대조·작업의 불변식·시험이 동작을 고정하는지·느슨해진 가드), `${CLAUDE_PLUGIN_ROOT}/src/skills/seam/reviewers/docs-reviewer.md`(문서·규칙 — 요구 채움·인용과 숫자 다시 재기·바뀐 규칙 문장과 결정 색인을 모든 규칙 문서에서 찾기·규칙 충돌).
   - 범위는 `$(python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/seam/main.py" base <ID>)..HEAD`(기준은 `<통합 브랜치>`·`origin/<통합 브랜치>`·요구사항 커밋 부모 가운데 가장 가까운 것 — 로컬 통합 브랜치가 낡아도 남의 커밋을 섞지 않게).
   - 프롬프트 맨 위에 `${CLAUDE_PLUGIN_ROOT}/src/skills/seam/subagent-header.md`의 ``` 블록(자리표를 채움), 리뷰어 프롬프트의 `{…}` 자리표도 채운다(`{SEARCH_DIRS}`는 설정 `seam.rule_docs`의 `search_dirs` — 비었으면 "없음(건너뜀)"으로 채우고, 문서 리뷰어는 낡은 언급 찾기를 건너뛴다). 지시에는 문제·읽을 것·낼 것만(작업 세션의 생각을 넣지 않는다).
   - 보고는 `agents/behavior-reviewer.md`·`agents/docs-reviewer.md`.
2. 기다리는 동안 할 일: 끝 검증(`step done` 안내의 1 — 바뀐 시험, `python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/seam/main.py" carryover`, 가벼운 표적 검사)을 돌려 `retro.md` `## 끝 검증`에 `- <명령> → <결과>`로 적고 회고 초안(`## 어긋난 것`)을 쓴다(틀 `${CLAUDE_PLUGIN_ROOT}/src/skills/seam/templates/retro.md`).
3. 보고가 오면 결과를 `review.md` `## 동작`·`## 문서·규칙`에 요약하고(틀 `${CLAUDE_PLUGIN_ROOT}/src/skills/seam/templates/review.md`) 커밋 `<ID> review: …`.

## 지킬 것

- 리뷰어 기다림(Stop 훅): 할 일이 모두 `[x]`이고 `run` 커밋 뒤 `review` 커밋 전, 보고가 다 있기 전 — `retro.md` `## 끝 검증`에 `- <명령> → <결과>` 줄이 없으면 턴을 끝낼 수 없다.

## 마치는 조건

- 보고 둘이 있고 `review.md` `## 동작`·`## 문서·규칙`이 채워져 커밋 `<ID> review: …`.

## 커밋

`<ID> review: …`

## 다음

고칠 것이 있으면 `python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/seam/main.py" step fix`, 없으면 `step done`.
