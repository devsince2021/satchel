# scroll

리드 세션이 작업 하나를 별도 작업 세션에 맡기면, 작업 세션이 설계 → 코드 전 검토 → TDD 구현 → 코드 뒤 검토 → 리뷰 반영 → 마무리를 스스로 돌며 결정·기록하고, 리드가 합치는 퀘스트 흐름을 담은 Claude Code 플러그인이다. 밖에서 쓰는 문은 스킬 `/quest` 하나다(플러그인 네임스페이스로는 `scroll:quest`).

```
⓪ 요구사항(리드) → 작업 세션 열기(리드) → ① 설계 → ② 코드 전 검토 → ③ 구현 → ④ 코드 뒤 검토 → ⑤ 리뷰 반영 → ⑥ 마무리 → 합치기(리드)
```

> [!WARNING]
> **작업 세션은 늘 `--dangerously-skip-permissions`로 뜬다.** 확인 창 없이 도구와 셸 명령을 실행한다는 뜻이다(아무도 보지 않는 세션이 확인 창에서 멈추지 않게 하려는 것이고, 설정으로 끌 수 없다).
> 플러그인은 그 대신 세 가지로 막는다.
> - 세션 settings deny — 리드 체크아웃·세션 기록 자리·플러그인 자리·홈 settings·넘길 일 장부·규칙 `src/rules/files.json`의 자리 쓰기, 규칙 `src/rules/git.json`의 git 명령, 질문 창.
> - PreToolUse 훅 `guard` — git 되돌리기류·리드 저장소 쓰기·deny 자리 읽기·쓰기를 셸 본문 안까지 풀어 읽어 막고, 커밋 제목과 단계 차례를 커밋하는 순간 본다.
> - 규칙 파일(files·git) — 막을 자리와 git 명령의 정본.
>
> 이것들은 OS 경계가 아니다. 작업 세션은 여는 사용자와 같은 권한으로 돌고, 훅은 실수와 습관적 우회를 막을 뿐이다. **믿을 수 있는 저장소와 기계에서만 쓴다.**

## 필요한 것

- Claude Code — 2.1.326에서 확인했다. 스킬, 하위 에이전트, 플러그인 훅(PreToolUse·Stop), `--plugin-dir`·`--name`·`--settings`, `SendMessage`, `ScheduleWakeup`(또는 `CronCreate`)를 쓴다.
- git, Python 3.9 이상(표준 라이브러리만), POSIX `sh`. `pgrep`이 있으면 합치기 전에 작업 세션 프로세스를 확인한다(없으면 건너뜀).
- superpowers 플러그인 — 스킬 `test-driven-development`(③)·`receiving-code-review`(⑤). 유일한 외부 플러그인 의존이다.
- 고른 터미널 프리셋에 따라 tmux 또는 Orca(아래 "터미널 프리셋"). `none`·`custom`이면 필요 없다.

## 설치

```
/plugin marketplace add <이 저장소 주소 또는 로컬 경로>
/plugin install scroll@satchel
```

리드 세션에만 설치하면 된다. 작업 세션은 `open`이 `--plugin-dir <이 플러그인 뿌리>`로 띄우므로 따로 설치하지 않는다.

프로젝트 쪽 준비:

1. 저장소 뿌리에 `.satchel/quest.json`을 두고 커밋한다(아래 "설정"). 작업 워크트리도 같은 설정을 읽으므로 커밋돼 있어야 열린다.
2. 작업 목록 `<quest.quests>/README.md`에 `## 작업 목록` 절과 표 머리 `| ID | 작업 | 상태 | 결정 |`, 넘길 일 장부 `<quest.quests>/carryover.md`에 표 머리 `| ID | 출처 | 받는 쪽 | 내용 | 상태 | 근거 |`를 둔다.
3. 작업 세션이 만들 수 있는 부산물(`__pycache__/` 등)은 `.gitignore`에 둔다 — 합치기는 작업 워크트리에 커밋 안 한 파일이 있으면 멈춘다.

## 설정 — `.satchel/quest.json`

가장 작은 예(필수 둘):

```json
{"branches": {"integration": "main"}, "session": {"terminal": "none"}}
```

다 적은 예:

```json
{
  "branches": { "integration": "main" },
  "quest":    { "quests": ".agents/quests", "guide_docs": ["AGENTS.md"], "lead": "lead", "rule_docs": {} },
  "session":  { "terminal": "tmux", "model": "opus" },
  "deliver":  { "verify": "npm test" }
}
```

받는 키는 아래 표뿐이고, 필수 밖은 바꿀 것만 적는다. 모르는 키·꼴이 틀린 값은 "설정 오류"로 멈춘다. 경로는 모두 저장소 뿌리 기준.

| 키 | 필수 | 기본값 | 뜻 |
| --- | --- | --- | --- |
| `branches.integration` | **필수** | — | 통합 브랜치. 리드 체크아웃이 이 브랜치여야 열고 합친다 |
| `session.terminal` | **필수** | — | 작업 세션을 띄우고 닫는 터미널 — `none`·`tmux`·`orca`·`custom`(아래 "터미널 프리셋") |
| `quest.quests` | 선택 | `".agents/quests"` | 기록 폴더. 그 아래 `<ID>-<슬러그>/`가 작업 하나. 작업 목록·장부·결정 폴더도 여기서 셈한다 |
| `quest.guide_docs` | 선택 | `["AGENTS.md"]` | 작업 세션·리뷰어가 결정·검토 전에 읽을 문서 |
| `quest.lead` | 선택 | `"lead"` | 메시지 꼴 `[<ID> → <이름>] …`의 리드 이름 |
| `quest.rule_docs` | 선택 | `{}`(꺼짐) | "바뀐 규칙 문장" 확인 — `{"patterns": [<규칙 문서 경로 정규식>…], "optional_prefix": "<회고 줄에서 생략해도 되는 머리>", "search_dirs": [<문서 리뷰어가 낡은 언급을 찾을 자리>…]}`. 켜면 작업 범위에서 바뀐 규칙 문서마다 회고 `## 바뀐 규칙 문장`에 줄이 있어야 끝 확인을 지난다 |
| `session.model` | 선택 | `"opus"` | 작업 세션의 `claude --model`, 리뷰어 하위 에이전트의 `model` |
| `session.launch`·`session.close` | `custom`일 때만(`launch`는 그때 필수) | `""` | 작업 세션을 띄울·닫을 셸 명령 틀(아래) |
| `deliver.verify` | 선택 | `""` | 합치기 전에 작업 브랜치 워크트리에서 돌릴 셸 명령. 종료 코드 0이어야 합친다. 비면 건너뜀 |

설정으로 받지 않는 값(설정에 적으면 모르는 키로 멈춘다):

| 값 | 어떻게 |
| --- | --- |
| 작업 ID · 장부 줄 ID | 고정 — `Q-NNN` · `C-NNN` |
| 작업 목록 · 넘길 일 장부 · 결정 폴더 | 셈 — `<quest.quests>/README.md` · `<quest.quests>/carryover.md` · `<quest.quests의 부모>/decisions` |
| 작업 범위 기준 후보 | 셈 — `origin/<branches.integration>`(없으면 건너뜀) |
| 작업 브랜치 · 작업 워크트리 | 고정 — `quest/<ID>-<슬러그>` · `<리드 저장소 부모>/<저장소 이름>-<id 소문자>`(리드 저장소 안이면 열지 않는다) |
| 세션 이름 · 세션 기록 자리 | 고정 — `quest <ID>` · `<git 공통 자리>/satchel/quest-sessions/<ID>/` |
| 작업 세션 권한 | 고정 — `--dangerously-skip-permissions` |
| 막을 자리 · 막을 git 명령 · 시험 파일 판정 · 단계 규칙 | 플러그인 규칙 [`src/rules/`](src/rules/README.md) — 이 플러그인을 쓰는 모든 프로젝트에 같다 |

### 터미널 프리셋

정의는 [`src/presets/terminals.json`](src/presets/README.md). `open`이 열기 전에 실행 파일·환경 변수를 확인하고, `merge`가 ③ 치우기에서 연 터미널로 닫는다(닫기는 실패해도 이어 간다).

| 프리셋 | 띄우기 | 닫기 | 필요 조건 |
| --- | --- | --- | --- |
| `none` | 띄울 명령만 찍는다 — 리드가 새 터미널에서 돌린다 | 건너뜀 | 없음 |
| `tmux` | 리드가 든 tmux 세션에 새 창(`tmux new-window -d -n "quest <ID>" …`) | `tmux kill-window` | PATH의 `tmux`, 환경 변수 `TMUX` |
| `orca` | 리드 탭의 Orca 워크트리 아래 새 탭(`orca terminal create …`) | 쉼을 기다린 뒤 탭 닫기 | `orca`(PATH 또는 `/Applications/Orca.app/Contents/Resources/bin/orca`), 환경 변수 `ORCA_WORKTREE_ID` |
| `custom` | 설정 `session.launch` 틀 | 설정 `session.close`(없으면 건너뜀) | `session.launch` |

custom 틀의 자리표는 셸 따옴표로 싸서 들어간다(글자 그대로의 중괄호는 `{{`·`}}`).

- `session.launch`: `{command}`(워크트리로 가서 claude를 띄우는 셸 한 줄)·`{worktree}`·`{id}`·`{title}`·`{settings}`·`{prompt_file}`·`{lead}`·`{branch}`. 예: `screen -dmS {id} sh -c {command}`.
- `session.close`: `{handle}`(띄울 때 출력 마지막 줄)·`{id}`·`{title}`·`{worktree}`·`{branch}`·`{settings}`.

## 쓰는 법

리드 세션에서 `/quest`를 부른다. 스킬이 부명령을 `python3 "${CLAUDE_PLUGIN_ROOT}/src/scripts/quest/main.py" <부명령>` 꼴로 부른다(세션 PATH에 싣는 명령은 없다). 셸·CI에서는 `python3 <플러그인 뿌리>/src/scripts/quest/main.py <부명령>`. 절차의 정본은 [`src/skills/quest/SKILL.md`](src/skills/quest/SKILL.md)(전체 그림·리드 몫)와 단계별 안내 `src/skills/quest/steps/<단계>.md`(작업 세션 몫)다.

### 리드가 하는 일

1. **요구사항** — `<quest.quests>/<ID>-<슬러그>/requirements.md`(틀 `src/skills/quest/templates/requirements.md`)와 작업 목록 줄을 쓰고 `git commit -m "<ID> req: 요구사항"`.
2. **열기** — `open <ID> --lead <리드 세션 이름>`(먼저 `--dry-run`). 작업 브랜치·워크트리·세션 settings(deny)·시작 지시를 만들고 터미널 프리셋으로 작업 세션을 띄운다.
3. **기다림** — 작업 세션이 보내는 결정 요청·막힘에 답한다. 작업 세션은 사용자에게 묻지 않는다.
4. **합치기** — 작업 세션이 끝을 알리면 `merge <ID>`(먼저 `--dry-run`): ① 확인(작업 세션이 멈췄고 끝 확인 통과) → ② deliver(리베이스 → `deliver.verify` → 기록 커밋 → fast-forward) → ③ 치우기(세션 닫기·워크트리·브랜치 지우기). 푸시는 하지 않는다.

### 작업 세션이 하는 일

단계마다 `step <단계>`로 들어가 그 단계 안내를 받고, 끝나면 `<ID> <단계>: …`로 커밋한다. 기록은 작업 폴더의 파일 넷(`requirements.md`·`plan.md`·`review.md`·`retro.md`).

| 단계 | 시작 명령 | 하는 일 |
| --- | --- | --- |
| ① 설계 | `step plan` | 코드 사실을 재고 결정·할 일을 `plan.md`에 |
| ② 코드 전 검토 | `step plan-review` | 리뷰어 하나(`plan-reviewer`) |
| ③ 구현 | `step test`·`step run` | 할 일마다 시험 커밋 → 구현 커밋(superpowers `test-driven-development`) |
| ④ 코드 뒤 검토 | `step review` | 리뷰어 둘(`behavior-reviewer`·`docs-reviewer`) |
| ⑤ 리뷰 반영 | `step fix` | 지적마다 `고침`·`기각`·`넘김`(superpowers `receiving-code-review`) |
| ⑥ 마무리 | `step done` | 끝 검증·회고, `end <ID>`로 끝 확인 |

### 부명령

| 부명령 | 누가 | 무엇 |
| --- | --- | --- |
| `open <ID> --lead <이름> [--dry-run\|--check-only] [--open <폴더>…]` | 리드 | 작업 세션 열기 |
| `step <단계>` | 작업 세션 | 단계 들어가기 — 앞 단계 커밋 확인·안내 찍기 |
| `status <ID>` | 누구나 | 커밋 제목으로 찾은 단계·첫 시각, 빠진 필수 단계 |
| `end <ID>` | 작업 세션 | 끝 확인 — 마지막 줄 `quest_check: 통과`/`막힘` |
| `base <ID>` | 작업 세션 | 작업 범위 기준 커밋 |
| `carryover` | 작업 세션 | 넘길 일 장부·작업 번호 확인 |
| `merge <ID> [--dry-run] [--keep] [--verified "<메모>"]` | 리드 | 합치기 |
| `rules-doc [--check]` | 플러그인을 고치는 이 | 문서의 생성 구역을 `src/rules/flow.json`에서 다시 만든다 |
| `guard`·`hold` | 플러그인 훅 | 아래 "훅" |

## 단계와 커밋

단계·커밋 제목·차례 규칙(정본 [`src/rules/flow.json`](src/rules/README.md), 이 구역은 부명령 `rules-doc`이 만든다):

<!-- rules:flow:begin -->
<!-- 이 구역은 부명령 `rules-doc`이 `src/rules/flow.json`에서 만든다. 손으로 고치지 않는다 — 고칠 것은 flow.json에 -->

| 단계 | 커밋 제목 | 누가 | 필수 |
| --- | --- | --- | --- |
| ⓪ 요구사항 | `<ID> req: …` | 리드 | 필수 |
| ① 설계 | `<ID> plan: …` | 작업 세션 | 필수 |
| ② 코드 전 검토 | `<ID> plan-review: …` | 작업 세션 | 필수 |
| ③ 구현 — 시험 | `<ID> test: #N …` | 작업 세션 | 없어도 됨 — 할 일이 모두 TDD 예외면 없다 |
| ③ 구현 | `<ID> run: #N …` | 작업 세션 | 필수 |
| ④ 코드 뒤 검토 | `<ID> review: …` | 작업 세션 | 필수 |
| ⑤ 리뷰 반영 | `<ID> fix: …` | 작업 세션 | 없어도 됨 — 고칠 것이 없으면 없다 |
| ⑥ 마무리 | `<ID> done: …` | 작업 세션 | 필수 |
| 합치기 | `<ID> merge: …` | 리드(부명령 `merge`) | 없어도 됨 — 끝 확인 뒤에 부명령 merge가 남긴다 |

- 커밋 제목은 `<ID> <단계>: …`, 단계 차례는 표 차례(`req`·`plan`·`plan-review`·`test`·`run`·`review`·`fix`·`done`·`merge`) — 부명령 `status`가 이 차례로 찍는다. 필수 단계 커밋이 없으면 끝 확인(부명령 `end`)이 "빠진 단계"로 막는다. 커밋이 없는 단계는 `git commit --allow-empty`.
- 여러 작업을 한 커밋에 묶은 제목 `<ID>·<ID> <단계>: …`은 단계 찾기(`status`·빠진 단계·Stop 훅)에서 각 작업의 그 단계로 친다. 할 일 커밋과 차례 판정은 `<ID> <단계>:` 꼴만 본다.
- 커밋하는 순간 PreToolUse 훅(부명령 `guard`)이 제목을 끝 확인과 같은 판정으로 본다 — 작업 세션은 이 작업 ID와 작업 세션 단계(`plan`·`plan-review`·`test`·`run`·`review`·`fix`·`done`), 리드 세션은 작업 ID로 시작하는 제목이 리드 단계(`req`)인지와 요구사항 파일을 새로 더하는 커밋의 ID. `merge` 단계 커밋은 부명령 `merge`만 남긴다. 제목은 `git commit -m`으로 쓴다(편집기·파일에서 읽는 꼴은 막는다).
- 할 일 번호: `test`·`run` 커밋은 제목에 할 일 번호 `#N`(여럿이면 `#2 #3`)을 넣는다 — `run` 커밋에 없으면 막는다. `test` 커밋은 시험 파일만(하나 이상) 바꾼다(시험 파일은 규칙 `src/rules/tests.json`의 `patterns`).
- 차례(끝 확인 `end`가 막는다):
  - 할 일 `#N`마다(`TDD 예외 — <까닭>` 할 일은 뺀다) `<ID> test: #N …` 커밋과 `<ID> run: #N …` 커밋이 있고, 첫 `test` 커밋이 첫 `run` 커밋보다 앞(topo 차례).
  - 단계마다 첫 커밋은 아래 "단계 사슬"의 앞 단계 첫 커밋 뒤(앞 단계 커밋이 없으면 "빠진 단계"가 막는다).
  - 첫 `test` 커밋 앞의 `plan`·`plan-review` 커밋은 구현 파일(시험 파일·기록 폴더·`.md` 밖)을 건드리지 않는다.
  - 첫 `plan-review` 커밋 때의 `plan.md`에 없던 `TDD 예외`는 `## 구현하며 바뀐 것`에 `할 일 N`과 까닭이 있어야 한다.

단계 사슬 — 작업 세션은 단계마다 시작 명령 `step <단계>`로 들어간다. 그 단계의 앞 단계 커밋이 있어야 들어가고, 커밋하는 순간 PreToolUse 훅이 같은 사슬과 시작 명령으로 들어왔는지를 다시 본다. 앞 단계는 단계 차례에서 그 단계 앞으로 거슬러 처음 만나는 필수 단계(사이의 필수 아닌 단계는 없어도 된다) — 단계에 `start_after`가 있으면 그 단계. 앞 단계로 되돌아가기는 된다. 리드 몫 단계는 시작 명령 대상이 아니다:

| 단계 | 시작 명령 | 앞 단계 커밋 |
| --- | --- | --- |
| ⓪ 요구사항 | 리드가 커밋 | — |
| ① 설계 | `step plan` | `<ID> req:` |
| ② 코드 전 검토 | `step plan-review` | `<ID> plan:` |
| ③ 구현 — 시험 | `step test` | `<ID> plan:` (`start_after`) |
| ③ 구현 | `step run` | `<ID> plan-review:` |
| ④ 코드 뒤 검토 | `step review` | `<ID> run:` |
| ⑤ 리뷰 반영 | `step fix` | `<ID> review:` |
| ⑥ 마무리 | `step done` | `<ID> review:` |
| 합치기 | 부명령 `merge` | `<ID> done:` |

- 리뷰어 기다림(작업 세션 Stop 훅이 되돌린다, 보고는 작업 기록 폴더 기준):
  - 코드 전 검토 중 = `plan` 커밋 뒤 `plan-review` 커밋 전, 보고 `agents/plan-reviewer.md`가 다 있기 전 — 할 일을 아직 안 썼거나 TDD 예외 아닌 할 일에 `<ID> test: #N …` 커밋이 없으면.
  - 코드 뒤 검토 중 = 할 일이 모두 `[x]`이고 `run` 커밋 뒤 `review` 커밋 전, 보고 `agents/behavior-reviewer.md`·`agents/docs-reviewer.md`가 다 있기 전 — retro `## 끝 검증`에 `- <명령> → <결과>` 줄이 없으면.

합치기(부명령 `merge`, 리드)의 단계 — 실패하면 출력에 멈춘 단계가 나온다. 합친 뒤 단계(푸시·알림)는 없다:

| 단계 | 하는 일 | 값 |
| --- | --- | --- |
| ① 확인 | 세션 기록이 있고 작업 세션 프로세스가 멈췄고 워크트리가 있다, 워크트리에서 끝 확인(end) 통과 | 고정 |
| ② deliver | deliver로 넣기 — 리베이스(통합 브랜치 위로) → 프로젝트 검사(비면 건너뜀) → 합치기 전에 기록 커밋(작업 목록 `끝`·장부 번호·회고 `## 닫을 장부 줄`대로 장부 줄 닫기)과 끝 확인 다시 → fast-forward | 밖에서 받음 — 설정 `deliver.verify` |
| ③ 치우기 | 세션 닫기(세션을 연 터미널 프리셋 또는 custom 닫기 틀) → 작업 세션 claude 멈춤 기다림 → 워크트리·작업 브랜치 지우기 → 세션 기록을 done/으로 | 고정 |
<!-- rules:flow:end -->

## 훅

`src/hooks/hooks.json`이 훅 셋을 건다 — PreToolUse `Bash`와 `Agent|Task|AskUserQuestion` → `guard`, Stop → `hold`. 판정은 **작업 세션**(작업 브랜치 `quest/<ID>-<슬러그>`이고 `open`이 남긴 세션 기록이 있는 세션)에서만 하고, 리드 세션에서는 커밋 제목만 본다. 그 밖의 세션·저장소에서는 아무것도 하지 않는다.

`guard`(PreToolUse), 작업 세션:

- 질문 창(`AskUserQuestion`), 공용 머리말(`src/skills/quest/subagent-header.md`) 없는 하위 에이전트.
- git 되돌리기류(`checkout`·`restore`·`stash`·`clean`·`switch`·`push`·`worktree`·`update-ref`·`reset --hard/--keep/--merge`·`branch` 지우기 등)와 규칙 `src/rules/git.json`의 git 명령, 리드 저장소를 가리키는 git 쓰기. `-C`·`env`·`sh -c`·`eval`·`$( )`·셸 본문 안까지 풀어 읽는다.
- deny 자리 읽기·쓰기 — 리다이렉션·`tee`·`cp`·`sed -i`·`patch`·`git apply`·인터프리터 본문의 경로까지.
- 셸 매개변수 가공(`${x%…}` 등)·glob 뒤 `..` — Claude Code가 확인 창을 띄워 세션이 멈추는 꼴.
- `git commit` — 제목이 `<이 작업 ID> <단계>: …` 꼴이 아니거나, 제목을 읽을 수 없는 꼴(편집기·`-F`·`-C`·`--fixup` 등)이거나, 단계 사슬의 앞 단계 커밋이 없거나 그 단계를 `step`으로 들어오지 않았으면 막는다.
- 나눌 수 없는 명령·판정 중 예외는 막는다(fail-closed).

`guard`, 리드 세션(quest 설정이 있는 저장소): `git commit`만 본다 — 작업 ID로 시작하는 제목은 리드 단계(`req`) 꼴이어야 하고, 요구사항 파일을 새로 더하는 커밋은 그 ID로 시작해야 한다.

`hold`(Stop), 작업 세션: `대기: 사용자`로 끝내기, 리뷰어를 기다리며 할 일이 남은 멈춤, 결정 요청 뒤 깨우기 예약 없음, 턴 끝 두 줄(`남은 지시:`·`대기:`)이 없는 멈춤, 지시 장부(`.quest-session/orders.md`)와 어긋난 멈춤을 되돌린다. 같은 사유로 세 번 되돌린 뒤에는 `대기: 리드 — 반복 막힘`으로 끝낼 수 있다.

## 규칙과 프리셋

이 플러그인을 쓰는 모든 프로젝트에 같은 규칙은 [`src/rules/`](src/rules/README.md)에 주제마다 파일 하나로 있다.

- `flow.json` — 단계·차례·커밋 제목 꼴·단계 사슬·리뷰어 기다림·합치기 단계.
- `tests.json` — 시험 파일로 치는 경로 꼴(언어별 흔한 자리·이름).
- `files.json` — 작업 세션이 쓰면 안 되는 워크트리 안 자리.
- `git.json` — 작업 세션이 쓰면 안 되는 git 명령(세션 deny와 훅 목록을 둘 다 여기서 만든다).

프리셋은 프로젝트가 설정으로 하나를 고르는 실행 수단이다 — 지금은 터미널 프리셋 [`src/presets/terminals.json`](src/presets/README.md) 하나.

## 한계

- deny와 훅은 OS 경계가 아니다(같은 사용자 권한). 조립한 글자, 변수에 담은 명령 이름, 이진 실행 파일 같은 남은 길은 규칙과 리드 검토가 맡는다.
- 인터프리터 본문(예: `python3 -c` 안의 `subprocess`) 안에서 부르는 `git commit`은 커밋하는 순간의 제목·단계 확인을 거치지 않는다. 인터프리터 본문의 git은 히스토리를 고치는 하위 명령만 막는다.
- Stop 훅 `hold`는 되돌릴 멈춤의 꼴을 목록으로 가진다 — 목록에 없는 꼴의 멈춤은 지나간다.
- 작업 세션은 리드와 같은 기계에서만 연다(다른 기계·ssh로 여는 갈래는 없다).
- 합친 뒤 푸시·알림 단계는 없다.

## 고치려면

이 플러그인을 고치는 사람·에이전트는 [`AGENTS.md`](AGENTS.md)를 먼저 읽는다(구조·의존 방향·시험·관례).

## 라이선스

MIT — 저장소 뿌리 [`LICENSE`](../../LICENSE).
