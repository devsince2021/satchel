# tailoring — 고치는 이를 위한 지침

이 플러그인을 고치는 코딩 에이전트가 먼저 읽는 문서다. 쓰는 법·설정 키·훅이 막는 것은 [`README.md`](README.md)에 있고 여기서는 가리키기만 한다.

## 원칙

- **흐름에 필요한 것만 담는다.** seam 흐름이 끊김 없이 도는 데 필요한 것만 두고 다른 기능을 섞지 않는다.
- **외부 의존은 Claude Code·git·Python 표준 라이브러리·superpowers 플러그인뿐이다.** 새 도구가 필요하면 플러그인 안으로 들여온다. tmux·Orca 같은 도구는 고른 프리셋으로만 들어오는 선택지다.
- **밖으로 내놓는 문은 스킬 `/seam` 하나다.** 세션 PATH에 싣는 명령 폴더는 두지 않는다. 입구 `src/scripts/seam/main.py`는 스킬 문서·훅·작업 세션 시작 지시만 전체 경로로 부른다. 합치기의 deliver도 입구 없이 `join`이 안에서 부르는 부품이다.
- **규칙의 정본은 `src/rules/`다.** 코드는 규칙 파일을 읽기만 하고, 문서의 규칙 구역(`<!-- rules:flow:begin -->`…`<!-- rules:flow:end -->`)은 부명령 `rules-doc`이 거기서 만든다.
- **설정·규칙·프리셋을 가른다.** 설정(`.studio/tailoring.json`)은 프로젝트의 이름·자리·고르는 것, 규칙(`src/rules/`)은 seam이 정해 모든 프로젝트에 같은 것, 프리셋(`src/presets/`)은 프로젝트가 설정으로 고르는 실행 수단이다. 설정 키를 늘리기 전에 셈하거나 고정할 수 있는지 먼저 본다.
- **장부는 리드만 쓴다.** 작업 세션은 넘길 일 장부를 고치지 않고 회고 `## 닫을 장부 줄`에 적으며, `join`의 기록 커밋이 옮겨 적는다(겹친 작업끼리 장부 충돌이 없게).
- **단계는 `step`으로 들어가고, 커밋 때 같은 확인을 한다.** 시작 명령은 미리 알려 주는 문, 커밋 때 `guard`의 확인은 빠져나갈 수 없는 문이다. 판정은 `src/scripts/seam/libs/commits.py` 한 자리를 `step`·`guard`·`inspect`가 같이 쓴다.

## 폴더 구조

```
.claude-plugin/plugin.json      이름·버전·설명·라이선스, 스킬 자리 ./src/skills · 훅 자리 ./src/hooks/hooks.json
README.md                       쓰는 사람용
AGENTS.md                       이 문서 — 고치는 이용
CLAUDE.md                       AGENTS.md를 가리키는 한 줄
src/                            플러그인 본체
  skills/seam/                 스킬 /seam — Claude Code가 읽는 절차 문서
    SKILL.md                    전체 그림·리드 몫
    steps/                      작업 세션 단계마다 안내 하나(<단계>.md)와 모든 단계 안내 common.md — 부명령 step이 찍는다
    reviewers/                  리뷰어 프롬프트(plan-reviewer·behavior-reviewer·docs-reviewer)
    templates/                  기록 틀(requirements·plan·review·retro)
    subagent-header.md          하위 에이전트 공용 머리말(guard가 확인)
  hooks/hooks.json              PreToolUse → guard, Stop → hold
  rules/                        seam이 작업 세션에게 지키게 하는 규칙 — 주제마다 파일 하나(README.md가 꼴과 고친 뒤 할 일)
    flow.json                   단계·차례·커밋 제목 꼴·단계 사슬·리뷰어 기다림·합치기 단계
    tests.json                  시험 파일 판정 꼴
    files.json                  작업 세션이 쓰면 안 되는 자리
    git.json                    작업 세션이 쓰면 안 되는 git 명령
  presets/                      프로젝트가 하나를 골라 쓰는 실행 수단(README.md가 꼴)
    terminals.json              터미널 프리셋(none·tmux·orca)
  scripts/                      코드(import 길에 이 자리를 두고 libs·seam·deliver를 이름으로 찾는다)
    libs/                       seam·deliver 공용 — settings.py(설정 파일 읽기·키 검사), git.py(git 부르기·뿌리·브랜치·짧은 해시)
    seam/
      main.py                   입구 — 부명령 이름(COMMANDS)을 보고 commands/의 파일 하나를 부른다
      commands/                 부명령마다 파일 하나(feed·step·status·inspect·base·join·carryover·guard·hold·rules_doc)
      libs/                     부명령들이 같이 쓰는 부품 — 설정 값(config)·규칙·프리셋 읽기(rules·presets)·커밋 판정(commits·gitcommit)·
                                훅 판정(block·bash·stop)·끝 확인 항목(checks/)·세션 열기(workspace·deny·prompts·terminals)·
                                합치기 기록(record·procs)·문서 생성(docgen) 등. 파일마다 머리 주석이 맡은 일을 적는다
    deliver/                    join ② 단계가 쓰는 부품 — config.py(branches·deliver만 요청), steps.py(확인·리베이스·검사·합치기)
test/                           시험 — src/와 같은 자리 꼴
  __init__.py · helpers.py      import 길·시험 설정과 규칙 사본
  scripts/{libs,seam/{commands,libs},deliver}/   src/scripts/의 파일 하나 = 같은 자리 시험 하나
  rules/ · presets/             규칙·프리셋 파일
  plugin/                       src/ 밖을 보는 시험 — 훅(test_hooks.py), 문서(test_docs.py)
```

## 의존 방향

- 입구 `main.py` → `commands/` → `seam/libs/` → 공용 `scripts/libs/`.
- `deliver`는 공용 `libs`만 쓰고 `seam`을 import하지 않는다. 공용 `libs`는 `seam`·`deliver`를 모른다. `seam/libs`는 `commands`를 모른다. `test/scripts/deliver/test_deliver.py`가 이 방향을 본다.
- `commands/`에는 부명령마다 파일 하나만 둔다(`rules-doc` → `rules_doc.py`). 여러 부명령이 쓰는 것은 `seam/libs/`로.

## 무엇을 고치려면 어디를

| 바꿀 것 | 고칠 곳 | 뒤따를 일 |
| --- | --- | --- |
| 단계·차례·커밋 제목 꼴·합치기 단계 | `src/rules/flow.json` | `rules-doc`으로 문서 구역 다시 만들기. 코드가 아는 종류를 더하면 `src/scripts/seam/libs/rules.py`·`docgen.py`(합치기 단계면 `commands/join.py`)도 |
| 작업 세션이 쓰면 안 되는 자리·git 명령 | `src/rules/files.json`·`src/rules/git.json` | 고정으로 막는 git 되돌리기류는 `src/scripts/seam/libs/bash.py` |
| 시험 파일 꼴 | `src/rules/tests.json` | — |
| 터미널 프리셋 더하기 | `src/presets/terminals.json` | README "터미널 프리셋" 표, `test/scripts/seam/libs/test_terminals.py`·`test/presets/test_presets.py`. 새 키·자리표면 `presets.py`·`terminals.py` |
| 단계 절차 글 | `src/skills/seam/steps/<단계>.md` | 절 `## 할 일`·`## 지킬 것`·`## 마치는 조건`·`## 커밋`·`## 다음`을 지킨다(`test_docs.py`가 본다) |
| 설정 키 | 공용 `src/scripts/libs/settings.py`(키 목록·필수·꼴) | README "설정" 표. 고정·셈 값은 `src/scripts/seam/libs/config.py` 머리 |
| 새 부명령 | `src/scripts/seam/commands/`에 파일 하나와 `main.py`의 `COMMANDS` | README·SKILL.md 부명령 표 |

규칙 파일의 꼴과 고친 뒤 할 일은 [`src/rules/README.md`](src/rules/README.md), 프리셋 꼴은 [`src/presets/README.md`](src/presets/README.md).

## 시험

저장소 뿌리에서 두 Python(3.9와 최신) 모두 통과해야 한다:

```
python3 -m unittest discover -s plugins/tailoring/test -t plugins/tailoring
/usr/bin/python3 -m unittest discover -s plugins/tailoring/test -t plugins/tailoring    # 3.9
```

한 파일만: 플러그인 뿌리(`plugins/tailoring`)에서 `python3 -m unittest test.scripts.seam.commands.test_join` 꼴.

함께 돌릴 것:

```
python3 plugins/tailoring/src/scripts/seam/main.py rules-doc --check   # 문서 생성 구역이 flow.json과 같은지 — 다르면 1
claude plugin validate .                                            # 장터
claude plugin validate plugins/tailoring                                # 플러그인
```

- 시험 자리: `src/`의 파일 하나 = `test/`의 같은 자리 시험 하나. `src/` 밖(훅·스킬 문서)을 보는 시험은 `test/plugin/`.
- 시험은 임시 git 저장소를 만들고 기본값과 다른 설정(`test/helpers.py` — 하위 폴더 기록·`dev/main` 통합 브랜치·`seam.rule_docs` 켬)과 더 좁은 규칙 사본을 써서, 값이 설정·규칙 파일에서만 오는지 본다. 한 시험만 다른 규칙·프리셋이 필요하면 `helpers.use_rules`.
- 진짜 tmux·Orca는 부르지 않는다 — `test_terminals.py`가 PATH 앞에 가짜 실행 파일을 둔다.
- `test/plugin/test_docs.py`는 생성 구역이 flow.json과 같은지, 플러그인 뿌리 문서(README·AGENTS·CLAUDE)와 `src/` 아래 `.md`에 적힌 `src/…` 경로·부명령·스킬 안 파일이 실제로 있는지, 단계마다 안내 파일 하나와 그 절이 있는지 본다. 경로나 이름을 바꾸면 문서도 같이 고친다.
- 끝 확인 시험(`test/scripts/seam/libs/test_checks.py`)은 git을 많이 불러 1분쯤 걸린다.

## 실제 세션으로 확인하기

시험은 훅을 함수와 프로세스로 부른다. Claude Code가 실제로 훅·스킬을 거는지는 짧은 세션으로 본다.

1. 임시 git 저장소를 만들고 `.studio/tailoring.json`에 `{"branches": {"integration": "main"}, "session": {"terminal": "none"}}`을 두고 커밋한다.
2. 그 저장소에서:
   ```
   claude --plugin-dir <이 플러그인 뿌리> -p --model haiku --dangerously-skip-permissions \
     "Bash로 git commit --allow-empty -m 'P-001 plan: x' 를 실행하고 결과를 그대로 적어라. 쓸 수 있는 스킬에 seam이 있는지도 답하라."
   ```
3. 리드 세션 판정이 걸리면 커밋이 막히고 `plan`은 작업 세션이 찍는 단계라는 `guard` 메시지가 돌아온다. 스킬은 `tailoring:seam`으로 보인다.

## 커밋과 문서 관례

- 파일 옮기기와 내용 바꾸기를 한 커밋에 섞지 않는다.
- 문서는 지금 상태만 적는다 — 바뀐 내력·옛 이름·판별 변경 기록을 두지 않는다(내력은 git 이력에).
- 문서와 코드 주석은 한국어(코드·명령·식별자는 그대로).
- 판을 올리면 `.claude-plugin/plugin.json`의 `version`과 저장소 뿌리 `README.md` 플러그인 표를 함께 고친다.

## 하지 말 것

- `src/rules/`에 코드에서만 쓰는 상수를 적지 않는다 — 규칙 파일은 작업 세션에게 지키게 하는 규칙만 담는다.
- 같은 규칙을 문서와 코드 두 곳에 손으로 적지 않는다 — 문서 쪽은 생성 구역이나 가리키는 문장으로.
- `commands/`에 부명령이 아닌 파일을 두지 않는다.
- 판정할 수 없는 경우를 "그냥 지나감"으로 만들어 건너뛰는 길을 내지 않는다. 작업 세션의 Bash 판정은 나눌 수 없거나 판정 중 예외면 막고(fail-closed), 단계 기록이 없으면 시작하지 않은 것으로 친다.
