presets/는 프로젝트가 설정으로 하나를 골라 쓰는 실행 수단을 모은 곳이다.

- `terminals.json` — 작업 세션을 띄우고 닫는 터미널 프리셋(none·tmux·orca). 설정 `session.terminal`이 이름으로 하나를 고른다(프리셋 밖은 `custom`).
- 새 프리셋은 `terminals.json`의 `presets`에 한 항목을 아래 꼴로 더한다 — 더하면 바로 `session.terminal`로 고를 수 있다.

`rules/`(quest가 작업 세션에게 지키게 하는 규칙)와 달리 고른 프로젝트만 쓰므로 의존이 아니다.

| 파일 | 무엇 | 고르는 설정 | 읽는 코드 | 돌리는 코드 |
| --- | --- | --- | --- | --- |
| `terminals.json` | 작업 세션을 띄우고 닫는 터미널 프리셋 — 프리셋마다 띄우기·닫기 명령 틀, 실행 파일, 필요한 환경 변수, 핸들 꺼내는 법 | `session.terminal`(프리셋 이름 또는 `custom`) | `src/scripts/quest/libs/presets.py`(쓰는 곳: `config.py` — 값 검사) | `src/scripts/quest/libs/terminals.py`(open이 띄우고 merge가 닫는다) |

깨진 파일·틀린 꼴은 규칙 파일과 같이 RuleError로 멈춘다. 프리셋을 더하거나 바꾸면 플러그인 README "터미널 프리셋" 표와 `test/scripts/quest/libs/test_terminals.py`(명령 꼴·핸들·닫기 차례를 가짜 실행 파일로 고정)·`test/presets/test_presets.py`도 맞춘다. 코드가 아는 키·핸들 꺼내는 법·자리표를 더하면 `presets.py`(검사)와 `terminals.py`(돌리기)를 고친다.

## terminals.json 꼴

`presets` — `{<이름>: <프리셋>}`. 이름은 소문자·숫자·`-`, `custom`은 쓸 수 없다(프로젝트 설정 `session.launch`·`close`를 쓰는 이름). 프로젝트 설정 `session.terminal`에 쓸 수 있는 값은 이 이름들과 `custom`이다 — 프리셋을 더하면 바로 고를 수 있다. 프리셋 키:

- `launch`: 띄우기 명령 틀(글 목록 — 셸을 거치지 않는다). 없으면 띄우지 않는 프리셋(`none` — 명령만 찍는다)이고, 그때는 다른 키를 두지 않는다.
- `bin`: `{"name": <실행 파일>, "fallbacks": [<절대 경로>…]}` — PATH의 이름, 없으면 fallbacks 가운데 실행할 수 있는 첫 자리. 둘 다 없으면 열기 전에 멈춘다. 틀의 `{bin}`이 이 자리.
- `env`: `{<환경 변수>: <없을 때 알릴 글>}` — 리드 세션 환경에 없으면 열기 전에 멈춘다. 틀에서 `{env:<이름>}`으로 쓴다(여기 적은 변수만).
- `handle`: 핸들 꺼내는 법 목록, 차례대로 처음 나온 것 — `{"json": "<점 경로>"}`(출력 JSON의 그 자리 글), `{"regex": "<정규식>"}`(출력에서 처음 맞는 곳), `{"last_line": "<정규식>"}`(마지막 출력 줄이 통째로 맞으면).
- `find`(선택): 핸들을 못 꺼냈을 때 다시 찾기 — `{"argv": <목록 명령 틀>, "list": "<출력 JSON의 목록 점 경로>", "title": "<제목 키>", "handle": "<핸들 키>", "tries": 1~10, "wait_seconds": 0~30}`. 세션 이름과 제목이 같은 항목의 핸들을 쓴다.
- `lost`(선택): 끝내 핸들이 없을 때 세션 기록(`launch_note`)과 출력에 남길 글. 열기는 되돌리지 않는다(세션은 떴을 수 있다).
- `close`: 닫기 명령 틀의 목록 — 차례로 돌리고 실패해도 이어 간다. 세션 기록에 핸들이 없으면 건너뛴다.

자리표: 띄우기·찾기 틀 `{bin}`·`{title}`(세션 이름)·`{command}`(워크트리로 가서 claude를 띄우는 셸 한 줄)·`{worktree}`·`{id}`, 닫기 틀 `{bin}`·`{title}`·`{worktree}`·`{id}`·`{handle}`, 그리고 `{env:<이름>}`. 글자 그대로의 중괄호는 `{{`·`}}`(예 tmux `#{{window_id}}`). 모르는 자리표·적지 않은 환경 변수는 RuleError.
