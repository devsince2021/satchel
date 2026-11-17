rules/는 quest가 작업 세션에게 지키게 하는 규칙과 그 판정 기준을 모은 곳이다.

- `flow.json` — 흐름 규칙(단계·차례·커밋 제목 꼴·차례 규칙·단계 사슬·리뷰어 기다림·합치기 단계). 읽는 쪽: 단계 시작(`step` — 단계 사슬)·끝 확인(`status`·`end`)·Stop 훅(`hold`)·PreToolUse 훅(`guard` — 커밋하는 순간의 제목 꼴·단계 사슬)·작업 세션 열기(`open` — `<ID> req:` 커밋)·합치기(`merge`)·문서 생성(`rules-doc`).
- `tests.json` — 시험 파일 판정(언어별 흔한 시험 자리·이름 꼴 하나). 읽는 쪽: 끝 확인(`end` — `test` 커밋·계획 커밋 판정).
- `files.json` — 파일: 작업 세션이 쓰면 안 되는 워크트리 안 자리. 읽는 쪽: 작업 세션 열기(`open` — 세션 settings deny `Edit(…)`, `--open` 확인).
- `git.json` — git: 작업 세션이 쓰면 안 되는 git 명령(명령마다 까닭). 읽는 쪽: 작업 세션 열기(`open` — 세션 settings deny `Bash(git …)`와 세션 기록의 guard 목록을 둘 다 여기서 만든다), PreToolUse 훅(`guard` — 세션 기록으로).

여기 있는 규칙은 이 파일이 정본이다 — 검사 코드는 이 파일을 읽고, 문서의 그 규칙 부분은 이 파일에서 만든다. 둘이 따로 고쳐져 어긋나지 않게 하려는 것이다. 프로젝트가 고르는 실행 수단(터미널 프리셋)은 규칙이 아니라 [`../presets/`](../presets/README.md)에 둔다. 어느 파일이 규칙 문서인가("바뀐 규칙 문장" 확인)는 프로젝트마다 달라 프로젝트 설정 `quest.rule_docs`로 받는다(플러그인 README "설정").

## 지금 있는 것

| 파일 | 무엇 | 읽는 코드 | 만들어지는 문서 구역 |
| --- | --- | --- | --- |
| `flow.json` | 흐름 규칙 — 단계 이름과 차례, 누가, 필수, 할 일 번호, 커밋 제목 꼴, 차례 규칙, 단계 사슬, 리뷰어 기다림의 단계·보고 짝, 합치기 단계 | `src/scripts/quest/libs/rules.py` 한 곳(쓰는 곳: `commits.py`(제목 판정 `title_problem` — 끝 확인과 커밋 때 훅이 같이 씀)·`checks/tdd.py`·`gitcommit.py`·`workspace.py`·`stop.py`·`record.py`·`commands/merge.py`·`commands/step.py`) | `skills/quest/SKILL.md` "단계와 커밋", `README.md` "단계와 커밋" — `<!-- rules:flow:begin -->`…`<!-- rules:flow:end -->` |
| `tests.json` | 시험 파일 판정 — 꼴(`patterns`) 하나 | `rules.py`의 `tests()`(쓰는 곳: `checks/tdd.py`) | 없음 |
| `files.json` | 작업 세션이 쓰면 안 되는 워크트리 안 자리(`paths`) | `rules.py`의 `files()`(쓰는 곳: `deny.py` — settings deny `Edit(<워크트리>/<자리>)`, `--open` 확인) | 없음(README "설정"이 이 파일을 가리킨다) |
| `git.json` | 작업 세션이 쓰면 안 되는 git 명령(`commands` — 명령·인자 조건·까닭) | `rules.py`의 `git()` — 막는 두 수단을 만든다(쓰는 곳: `deny.py` — settings deny `Bash(git …:*)`, `workspace.py` — 세션 기록의 guard 목록 `block_git`·`block_git_args`, 훅 `guard`는 세션 기록을 읽는다) | 없음(README "훅"·"설정"이 이 파일을 가리킨다) |

`files.json`·`git.json`·`tests.json`의 값은 프로젝트 설정으로 받지 않는다 — 이 플러그인을 쓰는 모든 프로젝트에 같다. 막는 git 명령은 `git.json` 하나의 목록이고, 세션 settings deny와 훅 guard 목록을 둘 다 여기서 만든다. 기록 파일의 필수 절, 리뷰 반영 낱말, 넘길 일 꼴, Stop 훅의 대기 줄 조건 같은 다른 규칙은 아직 코드에 있다. 찾는 대로 이 폴더에 파일로 옮긴다.

어느 파일에나 사람용 설명 칸 `설명`을 둘 수 있다(판정은 안 읽는다).

## files.json 꼴

- `paths`: 작업 세션이 못 고칠 워크트리 안 자리(glob, 비지 않은 글 목록). 부명령 `open`이 `Edit(<워크트리>/<자리>)` deny로 싣는다. `<자리>/**` 안 한 폴더는 `open --open <폴더>`로 연다. 프로젝트 설정에서 나오는 자리(넘길 일 장부 `<quest.quests>/carryover.md`)는 여기 적지 않고 open이 더한다.

## git.json 꼴

- `commands`: 막는 git 명령 목록. 항목마다 `command`(하위 명령 이름, 소문자·숫자·`-`) — **한 명령은 한 항목에만**, `args`(있으면 그 인자일 때만 막는다 — 빈칸·`:` 없는 인자 글의 비지 않은 목록, 예 `reset`의 `["--hard"]`; 하위 명령째 막으면 키를 뺀다), `why`(까닭 한 줄, 필수).
- 어느 수단으로 막을지는 코드(`rules.Git`)가 정하고, 모든 항목에 두 수단을 다 건다:
  - settings deny `Bash(git <command>:*)`, `args`가 있으면 인자마다 `Bash(git <command> <인자>:*)` — 훅이 안 걸려도 막히지만 앞머리만 맞춘다.
  - 세션 기록의 guard 목록 — `args` 없는 명령은 `block_git`, 있으면 `block_git_args`(`<command>:<인자>`). PreToolUse 훅이 `-C` 뒤·`sh -c`·`eval`·`$( )`·실행기 꼬리·`find -exec`·셸 본문 안까지 풀어 읽어 막는다. open이 세션 기록에 적고 훅은 기록을 읽으므로, 고친 값은 그 뒤 연 세션부터 걸린다.
- 이 목록과 따로, 훅 판정 코드(`src/scripts/quest/libs/bash.py`)가 고정으로 막는 git 되돌리기류(`worktree`·`update-ref`·`reset --keep/--merge`·`branch` 지우기 등)가 있다 — 플러그인 README "훅".

## tests.json 꼴

- `patterns`: 시험 파일로 치는 경로 정규식(하나라도 맞으면) — 언어별 흔한 자리·이름(`tests/`·`test/`·`__tests__/`·`spec/`·`src/test/`·`src/testFixtures/`, `test_*.py`·`*_test.py|go|rb|exs`·`*_spec.rb`·`*.test|spec.(c|m)js|ts|jsx|tsx`·`*Test(s).java|kt|cs|swift`·`*Spec.scala|groovy|kt`). `test` 커밋은 이 파일만(하나 이상) 바꿔야 하고, 첫 `test` 커밋 앞 계획 커밋은 시험 파일·기록 폴더·`.md` 밖 파일을 건드리지 않는다.
- 프로젝트 설정으로 받지 않는다(`quest.tests` 없음). 이 꼴로 못 가르는 파일은 그 할 일을 ② 코드 전 검토에서 `TDD 예외 — <까닭>`으로 푼다(SKILL ③). `patterns`·`설명` 밖의 키를 적으면 모르는 키로 멈춘다.

## flow.json 꼴

- `steps` — 단계 목록, **적은 차례가 단계 차례**(부명령 `status`가 이 차례로 찍는다). 단계마다:
  - `name`: 커밋 제목의 단계 낱말(소문자·숫자·`-`).
  - `stage`: 문서에 쓰는 이름(예 `② 코드 전 검토`). `by`: `리드` 또는 `작업 세션` — 그 커밋을 남기는 쪽. PreToolUse 훅이 커밋하는 순간 그쪽 세션의 제목만 받는다(`written_by` 단계는 부명령 merge만).
  - `required`: 참이면 끝 확인이 커밋을 요구한다("빠진 단계"). `note`: 필수가 아닐 때 문서에 붙일 까닭.
  - `todo`: 있으면 제목에 할 일 번호(`#N`)가 붙는 단계 — `필수`면 없을 때 막고, `선택`이면 받기만 한다.
  - `tests_only`: 참이면 그 커밋은 시험 파일만(하나 이상) 바꿔야 한다.
  - `written_by`: `quest merge` — 합치기가 쓰는 기록 커밋의 단계. 꼭 한 단계.
  - `start_after`: 단계 사슬의 앞 단계를 이 단계로 덮는다(그 단계보다 앞의 단계 이름). 지금은 `test`가 `plan` — 시험은 코드 전 검토를 기다리는 동안 쓴다.
- `commit` — 커밋 제목 꼴.
  - `title`: 제목 머리 꼴, 자리표 `{id}`·`{step}`(기본 `{id} {step}:`). 판정 정규식은 이 꼴과 단계 목록에서 만든다.
  - `todo_ref`: 할 일 번호 정규식 `pattern`(번호 그룹 하나), 문서용 꼴 `shape`·여럿 예 `many`.
  - `bundle`: 여러 작업을 한 커밋에 묶은 제목(`<ID>·<ID> <단계>:`)의 사이 글 `sep`과 다른 ID 정규식 `other_id` — 단계 찾기(status·빠진 단계·Stop 훅)만 받는다.
- `order` — 차례 규칙(끝 확인 `end`). 종류는 정해져 있고, 값은 단계 이름이다.
  - `todo_first` {`first`, `then`}: 할 일 `#N`마다(TDD 예외 뺌) 두 커밋이 있고 첫 `first`가 첫 `then`보다 앞.
  - `no_code_before` {`steps`, `until`}: 첫 `until` 커밋 앞의 `steps` 커밋은 구현 파일을 건드리지 않는다.
  - `exempt_fixed_at` {`step`, `record`}: 첫 `step` 커밋 때의 기록 파일 `record`에 없던 TDD 예외는 까닭이 있어야 한다.
- `chain` — 단계 사슬 {`needs`}: 단계에 들어갈 때(`step`)·그 단계를 커밋할 때(`guard`) 있어야 할 앞 단계 커밋, 끝 확인 차례(단계마다 첫 커밋은 앞 단계 첫 커밋 뒤)를 정하는 법. 값은 `previous_required` 하나 — 단계 차례에서 그 단계 앞으로 거슬러 처음 만나는 필수 단계(단계의 `start_after`가 있으면 그것). 판정은 `Flow.prerequisite` 한 곳.
- `reviews` — 리뷰어 기다림(작업 세션 Stop 훅). `before_code`(②)·`after_code`(④) 둘, 각 {`step`, `after`, `reports`}: `after` 커밋 뒤 `step` 커밋 전이고 보고 파일(`reports`, 작업 기록 폴더 기준)이 다 있기 전이면 기다리는 중.
- `merge` — 합치기(부명령 `merge`)의 단계 목록. 이름은 `check`·`deliver`·`cleanup` 셋을 이 차례로(코드가 이 차례로 돈다). 단계마다 `name`, `stage`(문서·출력에 쓰는 이름 — 멈추면 `quest merge — <stage>에서 멈춤`), `does`(하는 일), `takes`(밖에서 받는 설정 키 `묶음.키` 목록 — 비면 고정). 합친 뒤 단계(푸시·알림)는 두지 않는다.

모르는 키·없는 필수 키·없는 단계를 가리키는 값·정규식이 아닌 글은 `RuleError`로 멈춘다(규칙 파일 넷과 프리셋 파일 모두) — 사람이 부르는 부명령은 판정 전에 읽어(`rules.load_all()`, 프리셋은 설정을 읽을 때) `status|end|base|carryover`는 종료 2, `open|merge`는 종료 1(`규칙 오류: …`), 훅은 판정 불가로 지나가며 stderr 한 줄.

## 고친 뒤 할 일

1. 문서 생성 구역 다시 만들기(어디서든):
   ```
   python3 plugins/scroll/src/scripts/quest/main.py rules-doc           # 써 넣는다
   python3 plugins/scroll/src/scripts/quest/main.py rules-doc --check   # 견주기만 — 다르면 1
   ```
   생성 구역 밖 설명 글은 사람이 쓴 그대로 두므로, 바뀐 규칙을 가리키는 문장이 있으면 손으로 맞춘다.
2. 시험(저장소 뿌리에서, 두 python 모두):
   ```
   python3 -m unittest discover -s plugins/scroll/test -t plugins/scroll
   /usr/bin/python3 -m unittest discover -s plugins/scroll/test -t plugins/scroll
   ```
   `test/rules/test_rules.py`(flow·files·git·tests — git.json으로 만든 두 수단이 막는 범위 포함)·`test/presets/test_presets.py`·`test/plugin/test_docs.py`(생성 구역)가 생성 구역이 flow.json과 같은지, 정본 값, 깨진 파일이 오류인지, 파일을 바꾸면 판정이 따라 바뀌는지 본다. 다른 시험은 지금 규칙의 판정을 고정한다 — 규칙을 일부러 바꿨으면 그 시험도 함께 고친다.
3. 코드가 아는 종류(`order`·`reviews`·`merge`의 종류, `steps`의 키)를 더하거나 바꾸면 `src/scripts/quest/libs/rules.py`(검사)와 `src/scripts/quest/libs/docgen.py`(문장)도 고친다. 합치기 단계를 바꾸면 `src/scripts/quest/commands/merge.py`(차례)도.
