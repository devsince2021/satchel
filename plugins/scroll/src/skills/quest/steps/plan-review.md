# ② 코드 전 검토

## 할 일

1. `## 결정`을 커밋한 직후 독립 리뷰어 하나를 백그라운드로 띄운다(하위 에이전트, `model: <리뷰어 모델>` — 작업 세션과 같은 모델(설정 `session.model`)로 꼭 적는다, 읽기만) — 맨 위에 `${CLAUDE_PLUGIN_ROOT}/src/skills/quest/subagent-header.md`의 ``` 블록(자리표를 채움), 본문 `${CLAUDE_PLUGIN_ROOT}/src/skills/quest/reviewers/plan-reviewer.md`(`{MODE}` = `plan`, 보고 `agents/plan-reviewer.md`, 자리표를 채움 — `{GUIDE_DOCS}`는 `<안내 문서>`, `{RULE_DOCS}`는 설정 `quest.rule_docs`의 `patterns`(비었으면 "없음(건너뜀)" — 리뷰어는 바뀐 규칙 문장 대조를 하지 않는다), `{DECISIONS_DIR}`는 `<결정 폴더>`). 리뷰어는 규칙 충돌·과거 결정·사용자 패턴·결정의 꼴·코드와 부딪힘을 본다.
2. 기다리는 동안 할 일: ① 설계의 `## 할 일`을 마저 쓰고(`<ID> plan: 할 일`), 시험 쓰기 — `step test`를 부르고 할 일마다 지금 동작을 고정하거나 바뀔 동작을 빨강으로 보이는 시험을 써서 시험 커밋으로 남긴다. 그 일이 남은 채 턴을 끝내면 Stop 훅이 되돌린다(`대기: 리드 — 결정 요청`도). 리뷰 반영으로 시험이 바뀌면 다시 `test:` 커밋.
3. 보고가 오면 Critical·Important는 계획에 반영하고 `plan.md` `## 코드 전 검토`에 지적마다 한 줄(등급·한 일). 커밋 `<ID> plan-review: …`.

## 쓰는 리뷰어

- `${CLAUDE_PLUGIN_ROOT}/src/skills/quest/reviewers/plan-reviewer.md` + `${CLAUDE_PLUGIN_ROOT}/src/skills/quest/subagent-header.md`(머리말 없는 하위 에이전트는 PreToolUse 훅이 막는다).

## 지킬 것

- 리뷰어 기다림(Stop 훅): `plan` 커밋 뒤 `plan-review` 커밋 전, 보고 `agents/plan-reviewer.md`가 다 있기 전 — 할 일을 아직 안 썼거나 TDD 예외 아닌 할 일에 `<ID> test: #N …` 커밋이 없으면 턴을 끝낼 수 없다. 훅은 시험 커밋이 없는 번호를 보여 준다 — 번호마다 시험을 쓸 일이면 `test` 커밋, 시험이 필요 없는 일이면 plan.md 그 줄에 `TDD 예외 — <까닭>`(이 검토에서 확정). 필요 없는 시험을 만들어 채우지 않는다.
- 구현(`run`) 커밋은 이 단계의 `plan-review` 커밋 뒤다.

## 마치는 조건

- 보고 `agents/plan-reviewer.md`가 있고, 지적마다 `## 코드 전 검토`에 한 줄, 커밋 `<ID> plan-review: …`.

## 커밋

`<ID> plan-review: …`

## 다음

시험이 남았으면 `python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/quest/main.py" step test`, 구현은 `step run`.
