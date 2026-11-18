"""멈춤 판정 — 부명령 `hold`(Stop 훅, `seam/commands/hold.py`)가 부른다.

작업 브랜치(고정 꼴 `piece/<ID>-<슬러그>`)의 작업에서 마지막 답의 마지막 `대기:` 줄이 `사용자`로 시작하면 되돌린다 —
작업 세션은 사용자를 기다리지 않고 리드에게 결정 요청을 보낸다. 같은 사유로 연속 3회 되돌린 뒤에만
`대기: 리드 — 반복 막힘`으로 끝낼 수 있다(이른 반복 막힘은 되돌리되 횟수에 넣지 않는다).
하나 더 되돌린다 — 리뷰어가 돌고 있고(②·④, 단계 커밋과 보고 파일로 앎) 기다리는 동안 할 일
(② 시험 커밋, ④ 끝 검증 줄)이 남았는데 턴을 끝냄. `대기:` 줄이 무엇이든(`리드 — 결정 요청` 포함) 본다.
위 판정이 지나가면 작업 세션(세션 기록이 있는 것, `seam/libs/session.py`)에서 둘을 더 본다(일반 멈춤 막기 — 횟수에 넣지 않는다):
- 상시 프롬프트(세션 기록 `standing`): 마지막 답에 `남은 지시: …`와 `대기: …` 줄이 둘 다 없으면 되돌리고 상시 프롬프트를 다시 넣는다.
- 지시 장부(세션 기록 `orders`, 워크트리 `.seam-session/orders.md`): 열린 항목(`- [ ]`)이 있는데 마지막 답에 `남은 지시: 없음`,
  열린 항목에 `| 대기: <상대> — <이유>` 없음, 마지막 답을 읽지 못함 가운데 하나라도 맞으면 되돌린다.
`대기: 리드 — 결정 요청`이면 기록(`transcript_path`)에서 마지막 결정 요청 보냄 뒤 30분 안 깨우기 예약이 있는지도 본다.
횟수 파일은 작업 워크트리 git 자리(`git rev-parse --absolute-git-dir`)의 `stop-wait.json`(git이 잡지 않는다 — 합치기 전 깨끗함 검사에 안 걸림).
판정 불가(입력 깨짐·git 밖·작업 브랜치 아님·설정 오류·예상 밖 오류)는 0 — 그래서 리드 세션이나 다른 저장소의 세션에서
불려도 아무것도 하지 않는다. 작업 브랜치가 아니면 설정을 읽지 않고 말없이 0, 작업 브랜치에서 설정 오류(필수 키 없음 포함)는 0과 stderr 한 줄. 막으면 종료 2와 stderr 한 문단.
"""
import json
import os
import re
import subprocess
import sys
import time

from seam.libs import commits, config, rules
from seam.libs.checks import records, tdd
from seam.libs.context import Context, branch_work
from seam.libs.session import work_session
from seam.libs.text import read

STATE_FILE = None  # 시험이 바꾼다. None이면 작업 워크트리 git 자리의 stop-wait.json
REPEAT_LIMIT = 3
GIVE_UP = "리드 — 반복 막힘"


def user_wait(cfg):
    return (f"작업 세션은 사용자를 기다리지 않는다 — `{cfg.rel('pieces')}/{cfg.id_shape}-<슬러그>/asks-<n>.md`(물음, 선택지 둘 이상과 "
            f"권장·이유·틀렸을 때 비용)를 쓰고 커밋한 뒤 리드에게 `{cfg.to_lead(cfg.id_shape, '결정 요청: <경로>')}`를 보내고, "
            "30분 안 깨우기 예약을 걸고 `대기: 리드 — 결정 요청`으로 끝낸다(스킬 seam)")


EARLY = f"`대기: {GIVE_UP}`은 같은 사유로 {REPEAT_LIMIT}회 연속 되돌린 뒤에만 쓴다"


def state_file(ctx):
    if STATE_FILE:
        return STATE_FILE
    out = subprocess.run(["git", "-C", ctx.root, "rev-parse", "--absolute-git-dir"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise OSError("git 자리를 못 찾음")
    return os.path.join(out.stdout.strip(), "stop-wait.json")


def wait_line(message):
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip().startswith("대기:")]
    return lines[-1][len("대기:"):].strip() if lines else None


def is_give_up(reason):
    return bool(re.match(r"리드\s*[—–-]\s*반복 막힘", reason or ""))


def load_count(ctx):
    try:
        with open(state_file(ctx), encoding="utf-8") as f:
            found = json.load(f)
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def judge(ctx, payload):
    """막을 까닭(문자열) 또는 None. ctx는 payload `cwd`가 든 저장소의 문맥(git 밖이면 None)."""
    cwd = payload.get("cwd") or os.getcwd()
    if ctx is None:
        return None
    work = ctx.current_work(cwd)
    if work is None:
        return None
    reason = wait_line(payload.get("last_assistant_message"))
    if is_give_up(reason):
        return None if load_count(ctx).get("count", 0) >= REPEAT_LIMIT else EARLY
    if reason is not None and reason.startswith("사용자"):
        return f"`대기: {reason}` — {user_wait(ctx.cfg)}"
    if reason is not None and ASK_WAIT.match(reason):
        found = wake_after_ask(ctx.cfg, payload.get("transcript_path"))
        if found:
            return found
    return waiting(ctx, work)


ASK_WAIT = re.compile(r"리드\s*[—–-]\s*결정 요청")
WAKE_LIMIT = 1800


def _user_turn(content):
    """사용자 턴(깨우기 프롬프트·리드 답)인가 — tool_result만인 항목과 Stop 훅 되돌림 글은 아니다."""
    texts = [content] if isinstance(content, str) else [
        p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"] if isinstance(content, list) else []
    return any(t.strip() and not t.lstrip().startswith("Stop hook feedback") for t in texts)


def _tool_uses(path):
    """기록(JSONL)의 차례대로 (이름, 입력) — 사용자 턴은 (None, {}). 못 읽으면 None."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                content = (entry.get("message") or {}).get("content") if isinstance(entry, dict) else None
                if entry.get("type") == "user" if isinstance(entry, dict) else False:
                    if _user_turn(content):
                        out.append((None, {}))
                    continue
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict) and part.get("type") == "tool_use":
                        out.append((part.get("name"), part.get("input") or {}))
    except (OSError, TypeError):
        return None
    return out


def _is_wake(name, inp):
    if name == "CronCreate":
        return True  # cron 글은 풀지 않는다
    if name != "ScheduleWakeup" or inp.get("stop"):
        return False
    try:
        return 0 < float(inp.get("delaySeconds")) <= WAKE_LIMIT
    except (TypeError, ValueError):
        return False


def wake_after_ask(cfg, path):
    """`대기: 리드 — 결정 요청`이면 기록에서 마지막 결정 요청 보냄(SendMessage `message`에
    `결정 요청`) 뒤에 30분 안 깨우기 예약(ScheduleWakeup ≤ 1800초·stop 아님, CronCreate)이 있나 — 마지막 사용자 턴(깨우기 프롬프트·리드 답)보다도 뒤여야 한다. 없으면 되돌릴 문장.
    기록을 못 읽으면 판정 불가로 None."""
    uses = _tool_uses(path) if path else None
    if uses is None:  # 판정 불가 통과 — 꺼진 것을 한 줄 남긴다
        sys.stderr.write(f"[stop_wait] 기록을 못 읽어 깨우기 확인을 건넘: {path}\n")
        return None
    sent = [i for i, (name, inp) in enumerate(uses)
            if name == "SendMessage" and "결정 요청" in str(inp.get("message", ""))]
    if not sent:
        return ("`대기: 리드 — 결정 요청`인데 리드에게 결정 요청을 보낸 기록이 없다 — "
                f"`{cfg.to_lead(cfg.id_shape, '결정 요청: <asks 경로>')}`를 보내고 30분 안 깨우기 예약을 건 뒤 끝낸다(스킬 seam)")
    users = [i for i, (name, _) in enumerate(uses) if name is None]
    since = max(sent[-1], users[-1] if users else -1)  # 깨어난 턴 앞의 옛 예약은 이미 울렸다
    if not any(_is_wake(name, inp) for name, inp in uses[since + 1:]):
        return ("결정 요청을 보낸 뒤 30분 안 깨우기 예약(ScheduleWakeup delaySeconds ≤ 1800 또는 CronCreate)이 없다 — "
                "예약을 걸고 `대기: 리드 — 결정 요청`으로 끝낸다(스킬 seam)")
    return None


def waiting(ctx, work):
    """리뷰어가 돌고 있고 기다리는 동안 할 일이 남았으면 되돌릴 문장, 아니면 None. 단계·보고 파일은 흐름 규칙 `reviews`:
    ② 중(`before_code`) = `after` 커밋 있음·`step` 커밋 없음·보고(`reports`) 중 없는 것 → 남은 일: TDD 예외 아닌 할 일의 시험 커밋(`order.todo_first.first`).
    ④ 중(`after_code`) = 할 일 모두 `[x]`·`after` 커밋 있음·`step` 커밋 없음·보고 중 없는 것 → 남은 일: retro 끝 검증 줄."""
    folder = ctx.piece_dir(work)
    plan_path = os.path.join(folder, "plan.md") if folder else None
    if plan_path is None or not os.path.exists(plan_path):
        return None
    flow = rules.flow()
    before, after = flow.reviews["before_code"], flow.reviews["after_code"]
    have = {s for s, _ in commits.steps_of(ctx, work)}
    todos = tdd.todos(read(plan_path))

    def reviewing(review):
        return (review["after"] in have and review["step"] not in have
                and not all(os.path.exists(os.path.join(folder, r)) for r in review["reports"]))

    if reviewing(before):
        if not todos:  # `## 결정`까지 커밋하고 리뷰어를 띄운 뒤 할 일을 아직 안 씀
            return ("코드 전 검토(리뷰어)를 기다리는 동안 할 일이 남았다 — 계획 `## 할 일`(번호·고정할 시험)을 쓰고 "
                    f"`{flow.title(work, before['after'])} …`로 커밋한 뒤 시험을 쓴다(`step {before['after']}`·`step {before['step']}` 안내)")
        first = flow.order["todo_first"]["first"]
        tested = set().union(*[nums for _, step, nums in commits.todo_commits(ctx, work) if step == first])
        left = [n for n, _, tail in todos if not tdd.EXEMPT.search(tail) and n not in tested]
        if left:  # 근거(시험 커밋 없는 번호)와 고를 길 둘. 이미 시험 커밋이 있으면(`step test`로 들어왔다) 다시 부르라고 하지 않는다
            enter = "" if tested else f"`python3 {config.ENTRY} step {first}`로 들어가 "
            return (f"코드 전 검토(리뷰어)를 기다리는 동안 할 일이 남았다 — plan.md `## 할 일` 가운데 시험 커밋이 없는 번호: "
                    + ", ".join(f"#{n}" for n in left) + f". 번호마다 시험을 쓸 일이면 {enter}`{flow.title(work, first)} #N …`로 커밋하고, "
                    "시험이 필요 없는 일이면 plan.md 그 줄에 `TDD 예외 — <까닭>`을 적는다(코드 전 검토에서 확정).")
    if todos and all(done for _, done, _ in todos) and reviewing(after):
        retro = os.path.join(folder, "retro.md")
        text = read(retro) if os.path.exists(retro) else ""
        if not records.has_verify_line(text):
            return (f"코드 뒤 검토(리뷰어 둘)를 기다리는 동안 할 일이 남았다 — 끝 검증(바뀐 시험·`python3 {config.ENTRY} carryover`·프로젝트 검사 명령)을 "
                    f"돌려 `retro.md` `## 끝 검증`에 `- <명령> → <결과>`로 적고 회고 초안을 쓴다(`step {after['step']}` 안내)")
    return None


# ---- 상시 프롬프트·지시 장부(세션 기록의 `standing`·`orders`가 있을 때) ----
# 턴 끝 두 줄: `남은 지시: <없음 | 남은 것과 이유>`와 `대기: <기다리는 상대>`(앞 공백·굵게 `**` 허용).
WAIT_LINE = re.compile(r"^[ \t]*(?:\*\*)?대기(?:\*\*)?[ \t]*:[ \t]*\S", re.M)
LEFT_LINE = re.compile(r"^[ \t]*(?:\*\*)?남은 지시(?:\*\*)?[ \t]*:[ \t]*\S", re.M)
RETRY_SECONDS = 2  # 기록 파일의 마지막 답이 아직 안 써졌을 수 있어 한 번 더 본다. 시험이 0으로 바꾼다


def has_end_lines(text):
    return bool(text) and bool(WAIT_LINE.search(text)) and bool(LEFT_LINE.search(text))


def last_text(path):
    """기록(JSONL)의 마지막 assistant 글 블록(끝 100줄 안). 못 읽으면 ""."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            rows = [ln for ln in f if '"role":"assistant"' in ln][-100:]
    except (OSError, TypeError):
        return ""
    last = ""
    for line in rows:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        for part in ((entry.get("message") or {}).get("content") or []) if isinstance(entry, dict) else []:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                last = part["text"]
    return last


def standing_reason(record, payload):
    """상시 프롬프트 — 마지막 답에 턴 끝 두 줄이 없으면 막고 상시 프롬프트를 다시 넣는다. 상시 프롬프트 파일이 없으면 None."""
    marker = record.get("standing")
    if not marker or not os.path.isfile(marker):
        return None
    if has_end_lines(payload.get("last_assistant_message")):
        return None
    path = payload.get("transcript_path")
    if path and os.path.isfile(path):
        if has_end_lines(last_text(path)):
            return None
        time.sleep(RETRY_SECONDS)
        if has_end_lines(last_text(path)):
            return None
    return "[랄프 루프] 턴이 '남은 지시: …'와 '대기: <기다리는 상대>' 줄 없이 끝났다. 이어 간다.\n\n" + read(marker)


OPEN_ORDER = re.compile(r"^\s*- \[ \]")
WAITING = re.compile(r"\|\s*대기\s*:\s*\S")


def _says_none(line):
    """`남은 지시: 없음`(앞뒤 공백·굵게·글머리 기호 허용, 값이 `없음`으로 시작)."""
    m = re.match(r"\s*(?:[-*]\s+)?(?:\*\*)?남은\s*지시(?:\*\*)?\s*:(.*)$", line)
    return bool(m) and re.match(r"없음(?![0-9A-Za-z가-힣])", m.group(1).replace("*", "").strip()) is not None


def orders_problem(path, msg, have):
    """지시 장부 대조 — 막을 글 또는 None. 열린 항목(`- [ ]`)이 있는데 ① 마지막 답에 `남은 지시: 없음`
    ② 열린 항목에 `| 대기: <상대> — <이유>`가 없음 ③ 마지막 답을 읽지 못함(have False)."""
    try:
        rows = read(path).splitlines()
    except OSError:
        return f"[지시 목록] {path}를 읽지 못했다. 파일을 확인한 뒤 끝낸다."
    opened = [r.strip() for r in rows if OPEN_ORDER.match(r)]
    if not opened:
        return None
    nowait = [o for o in opened if not WAITING.search(o)]
    problems = []
    if not have:
        problems.append("마지막 답을 읽지 못해 '남은 지시: 없음' 여부를 확인할 수 없다.")
    elif any(_says_none(line) for line in msg.splitlines()):
        problems.append(f"열린 지시 {len(opened)}개가 있는데 마지막 답에 '남은 지시: 없음'이 있다.")
    if nowait:
        problems.append(f"대기 사유 없는 열린 지시가 {len(nowait)}개 있다.")
    if not problems:
        return None
    listed = nowait + [o for o in opened if WAITING.search(o)]
    more = f"\n(외 {len(listed) - 5}개)" if len(listed) > 5 else ""
    return (f"[지시 목록] 턴을 끝낼 수 없다({path}).\n" + "\n".join("· " + p for p in problems)
            + "\n열린 항목:\n" + "\n".join(listed[:5]) + more
            + "\n끝냈으면 [x]와 확인 근거, 못 끝내면 '| 대기: <상대> — <이유>'를 그 줄에 붙여라. "
            "확인 근거는 파일·해시·로그 경로이고 하위 에이전트·다른 세션의 보고는 근거가 아니다. 열린 항목이 남으면 '남은 지시:'에 그 항목을 적는다.")


def orders_reason(record, payload):
    """지시 장부 파일(세션 기록 `orders`)이 있을 때만. 훅 입력의 마지막 답이 있으면 그것만, 없으면 기록 파일의 마지막 글
    (막게 되면 한 번 더 본다), 그것도 없으면 읽지 못함."""
    path = record.get("orders")
    if not path or not os.path.isfile(path):
        return None
    msg = payload.get("last_assistant_message") or ""
    if msg.strip():
        return orders_problem(path, msg, True)
    transcript = payload.get("transcript_path")
    if transcript and os.path.isfile(transcript):
        def check():
            text = last_text(transcript)
            return orders_problem(path, text, bool(text.strip()))
        found = check()
        if found:
            time.sleep(RETRY_SECONDS)
            found = check()
        return found
    return orders_problem(path, "", False)


def session_reasons(payload):
    """작업 세션(세션 기록 있음)의 상시 프롬프트·지시 장부 막음 — 막을 글들."""
    found = work_session(payload.get("cwd") or os.getcwd())
    if found is None:
        return []
    record = found[2]
    return [r for r in (standing_reason(record, payload), orders_reason(record, payload)) if r]


def turn_mark(payload):
    """이 멈춤의 열쇠 — [세션 id, 기록 파일 크기]. 같은 멈춤에 두 번 불린 훅은 같은 열쇠를 본다(되돌린 뒤의 다음 멈춤은
    기록이 늘어 열쇠가 바뀐다). 기록이 없으면 None(가르지 않는다)."""
    path = payload.get("transcript_path")
    try:
        size = os.path.getsize(path) if path else None
    except OSError:
        size = None
    return None if size is None else [payload.get("session_id") or "", size]


def verdict(payload):
    """훅 입력(사전)을 판정한다 — 되돌릴 글(stderr에 쓸 한 문단) 또는 None(지나감). 판정 불가는 stderr 한 줄을 쓰고 None."""
    ctx = None
    try:
        if not isinstance(payload, dict):
            return None
        if branch_work(payload.get("cwd") or os.getcwd()) is None:
            return None  # 작업 브랜치가 아니면 설정을 읽지 않고 지나간다(설정 없는 저장소·리드 세션)
        ctx = Context.from_cwd(payload.get("cwd") or os.getcwd())
        found = judge(ctx, payload)
    except Exception as e:  # noqa: BLE001  예상 밖 오류는 판정 불가로 통과, 한 줄만 남긴다
        sys.stderr.write(f"[stop_wait] 판정 불가로 통과: {type(e).__name__}: {e}\n")
        return None
    if found is None:
        if ctx is not None:  # git 밖이면 횟수 파일 자리도 없다
            try:
                os.remove(state_file(ctx))
            except OSError:
                pass
        try:
            more = session_reasons(payload) if ctx is not None else []
        except Exception as e:  # noqa: BLE001  세션 기록을 못 읽으면 판정 불가로 통과
            sys.stderr.write(f"[stop_wait] 상시 지시·지시 장부 판정 불가로 통과: {type(e).__name__}: {e}\n")
            return None
        return "\n\n".join(more) + "\n" if more else None
    prev = load_count(ctx)
    count = prev.get("count", 0)
    turn = turn_mark(payload)
    if found != EARLY:  # 이른 반복 막힘은 횟수에 넣지 않는다 — give-up을 거듭 써서 횟수를 채우지 못하게
        if turn is not None and prev.get("turn") == turn and prev.get("key") == found:
            pass  # 같은 멈춤에 훅이 두 번 불렸다(같은 플러그인이 홈 설치와 --plugin-dir 둘로 실림) — 한 번만 센다
        else:
            count = count + 1 if payload.get("stop_hook_active") and prev.get("key") == found else 1
        try:
            with open(state_file(ctx), "w", encoding="utf-8") as f:
                json.dump({"key": found, "count": count, "turn": turn}, f, ensure_ascii=False)
        except OSError as e:  # 횟수를 못 적어도 막는다(반복 막힘 탈출만 늦어진다)
            sys.stderr.write(f"[stop_wait] 횟수 파일을 못 적음: {e}\n")
    tail = (f" 같은 사유로 {count}회 되돌렸다 — 고칠 수 없으면 `대기: {GIVE_UP}`으로 끝낸다."
            if count >= REPEAT_LIMIT else "")
    return f"[stop_wait] 끝낼 수 없다: {found}.{tail}\n"
