"""작업 세션에 주는 글 — 시작 지시(`task.md`)·상시 프롬프트(`standing.md`)·지시 장부 첫 꼴(`orders.md`)·연 뒤 안내 줄.
부명령 `feed`가 쓴다. 상시 프롬프트는 Stop 훅이 턴 끝 두 줄 없이 멈춘 턴에 다시 넣는다.
"""
import os
from datetime import datetime

from seam.libs.workspace import seam_entry


def ask_guide(work, folder, cfg):
    """결정 요청 길."""
    rule_text = ("규칙 문장은 멈추지 않고 스스로 정해 고치고 `retro.md` `## 바뀐 규칙 문장`에 옛 → 새로 남긴다(리드가 합친 뒤 보고한다). "
             if cfg.rule_docs.on else "")
    return (f"사용자에게 묻지 않는다. {rule_text}사용자가 정할 자리(되돌릴 수 없는 일 — 삭제·푸시·병합 / 확정 룰끼리 충돌 / 요구사항 뒤집힘)에서만 "
            f"`{cfg.rel('pieces')}/{folder}/asks-<n>.md`(물음, 선택지 둘 이상과 각각의 권장·이유·틀렸을 때 비용·근거, 같이 나온 물음은 한 파일)를 "
            f"쓰고 커밋한 뒤 리드에게 `{cfg.to_lead(work, '결정 요청: <경로>')}`를 보내고, 30분 안 깨우기 예약을 걸고, "
            f"마지막 줄 `대기: 리드 — 결정 요청`으로 턴을 끝낸다(기다리는 동안 할 수 있는 일은 먼저 한다). "
            f"리드 답 `{cfg.from_lead(work, '결정: <n> <고른 것>')}`이 오면 ask 파일 끝 `## 결정`과 "
            f"`plan.md` `## 결정`에 `리드 전달(사용자 결정 <날짜>)`을 적고 잇는다.")


def delivery_guide(p):
    """리드에게 전달이 안 될 때의 길 — 시작 지시에 싣는다(단계 안내 common.md에도 같은 뜻)."""
    return ("`SendMessage`가 도구 목록에 안 보이면 `ToolSearch`(`select:SendMessage`)로 먼저 불러온다. 리드에게 전달이 실패하면 한 번만 더 해 보고, "
            f"그래도 안 되면 지시 장부 `{p['orders']}`에 그 전달을 열린 줄로 적고 `| 대기: 리드 — 전달 실패`를 붙인 뒤 일은 이어 간다"
            "(전달 실패는 `retro.md` `## 어긋난 것`에도 한 줄). 그 줄이 열린 채 턴을 끝낼 때는 `남은 지시:`에 그 전달을 적는다.")


def task_text(p, cfg):
    """작업 세션 시작 지시(`<세션 기록>/task.md`) — 세션이 처음 읽는다."""
    work, folder = p["work"], p["folder"]
    pieces = cfg.rel("pieces")
    return f"""# {work} 작업 세션 시작 지시

작업: {work} · 요구사항: `{pieces}/{folder}/requirements.md` · 스킬: `seam`(작업 세션 몫 ①~⑥) · 브랜치: `{p['branch']}`

- 리드 세션 이름: {p['lead_name']}. 리드에게는 `SendMessage`(to: `{p['lead_name']}`)로 `{cfg.to_lead(work, '<한 줄>')}`을 보낸다. 리드의 답은 `{cfg.from_lead(work, '…')}`로 온다 — 받은 메시지의 `from`으로 답한다.
- {delivery_guide(p)}
- 가장 먼저 리드에게 `{cfg.to_lead(work, '시작: ①')}`을 보내고, 먼저 `python3 {seam_entry(p)} step plan`을 불러 나온 안내를 따른다. ⓪(요구사항)은 리드가 끝냈으니 ①~⑥을 끝까지 한다 — 단계마다 먼저 `python3 {seam_entry(p)} step <단계>`(`plan`·`plan-review`·`test`·`run`·`review`·`fix`·`done`)를 부르고 그 안내를 따른다(시작 명령 없이 그 단계를 커밋하면 훅이 막는다). 결정 번호는 요구사항 머리의 범위만 쓴다.
- 고치는 곳은 이 워크트리(`{p['worktree']}`)뿐이다. 리드 체크아웃과 막힌 자리(세션 deny — 플러그인 규칙 `src/rules/files.json`)는 고치지 않는다. 막힌 자리를 고쳐야 하면 리드에게 `{cfg.to_lead(work, '…')}`로 알린다.
- 이 브랜치에만 커밋한다. 병합·푸시는 리드 일이다.
- 리뷰어 등 하위 에이전트는 `model: {cfg.model}`로 띄운다 — 이 세션과 같은 모델(설정 `session.model`). 빼면 다른 모델로 뜬다.
- {ask_guide(work, folder, cfg)}
- 막힌 명령을 스크립트·인터프리터로 돌아가지 않는다 — 되돌릴 일은 커밋으로 하고, 막힌 일이 꼭 필요하면 리드에게 `{cfg.to_lead(work, '[막힘] <막힌 명령과 까닭>')}`을 보낸다.
- 상시 지시는 `{p['standing']}`에 있다 — 지시 장부 `{p['orders']}`와 턴 끝 두 줄(`남은 지시:`·`대기:`). 그 줄 없이 턴을 끝내면 Stop 훅이 그 글을 다시 넣는다.
- 할 일이 없을 때만 답 마지막 줄을 `대기: <기다리는 상대>`로 쓰고 끝낸다(`대기: 사용자`는 Stop 훅이 되돌린다).
- ⑥ 끝에 `python3 {seam_entry(p)} inspect {work}`가 `seam_check: 통과`면 리드에게 `{cfg.to_lead(work, f'끝: {pieces}/{folder}/retro.md')}`를 보낸다.
"""


def standing_text(p, cfg):
    """상시 프롬프트(`<세션 기록>/standing.md`) — Stop 훅이 턴 끝 두 줄 없이 멈춘 턴에 다시 넣는다."""
    work, folder = p["work"], p["folder"]
    guides = "·".join(cfg.rel("guide_docs")) or "프로젝트 안내 문서"
    return f"""{work} 작업 세션(seam). 리드 세션이 열었다. {guides}를 따른다.

지시는 {p['prompt_file']}에 있다. 단계마다 먼저 `python3 {seam_entry(p)} step <단계>`를 부르고 나온 안내를 따른다(처음은 `step plan`). 진행은 {p['orders']}에 적는다: 할 일은 `- [ ]`, 끝나면 `[x]`와 `| 확인: …`. 대기로 턴을 끝낼 때는 열린 줄에 `| 대기: <상대> — <이유>`를 붙이고 다시 일을 시작하면 뗀다.
리드 세션 이름: {p['lead_name']}. 리드에게는 `SendMessage`(to: `{p['lead_name']}`)로 `{cfg.to_lead(work, '<한 줄>')}`을 보낸다. 리드의 답은 `{cfg.from_lead(work, '…')}`로 온다 — 받은 메시지의 `from`으로 답한다.

{ask_guide(work, folder, cfg)}

할 일이 없을 때만 답 마지막에 두 줄을 쓰고 끝낸다.
남은 지시: <없음 | 남은 것과 지금 못 하는 이유>
대기: <기다리는 상대>
"""


def orders_text(p):
    """지시 장부 첫 꼴 — 열린 지시 하나(①~⑥)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"# 지시 목록 ({p['work']})\n\n- [ ] {now} | 리드 | {p['work']} ①~⑥(스킬 seam) — {p['prompt_file']}\n"


def after_open_lines(p, cfg, launched):
    first = (f"확인: 작업 세션의 첫 메시지 `{cfg.to_lead(p['work'], '시작: ①')}`을 기다린다. 오면 보낸 이(from)를 "
             f"{os.path.join(p['session_dir'], 'session.json')}의 session_name에 적는다.")
    if launched:
        return [first]
    return [f"세션 띄우기: 설정 `session.terminal`이 {cfg.terminal}(띄우지 않음) — 아래 명령을 새 터미널에서 돌려 작업 세션을 띄운다.",
            p["command"], first]
