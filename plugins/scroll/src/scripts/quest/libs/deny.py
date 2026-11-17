"""작업 세션 settings의 deny 만들기 — 부명령 `open`이 세션 settings에 싣는다.

deny만 싣는다: 홈 settings deny(리드 경로는 워크트리로 옮김)·리드 체크아웃·세션 기록 자리·플러그인 자리·홈 settings.json,
규칙 `src/rules/files.json`의 자리(워크트리 안)·`src/rules/git.json`에서 만든 Bash 앞머리, 넘길 일 장부(`<quest.quests>/carryover.md` — 리드만 쓴다),
질문 창(`AskUserQuestion`). `--open <폴더>`는 막힌 자리 안 한 폴더만
열어 준다(덮는 줄을 빼고 형제를 하나씩 막는다). 훅은 넣지 않는다 — 플러그인 훅이 건다.
"""
import json
import os

from quest.libs import rules


def _covering(rel, cfg):
    """rel을 덮는 deny 항목(`<자리>/**`, 규칙 `src/rules/files.json`의 paths) — 없으면 None."""
    for sub in rules.files().paths:
        if sub.endswith("/**") and (rel + "/").startswith(sub[:-2]):
            return sub
    return None


def open_problems(p, cfg):
    """`--open <폴더>`: 리드 체크아웃에 있고 막힌 자리(규칙 `src/rules/files.json` paths의 `<자리>/**`) 안인 폴더만."""
    out = []
    for rel in p.get("open") or ():
        rel = rel.strip(os.sep)
        sub = _covering(rel, cfg)
        if ".." in rel.split(os.sep):
            out.append(f"열 폴더에 `..`이 있다: {rel}")
        elif not os.path.isdir(os.path.join(p["lead_top"], rel)):
            out.append(f"열 폴더가 없다: {rel}")
        elif not sub:
            out.append(f"열 폴더가 막힌 자리 안이 아니다: {rel}")
        elif rel == sub[:-3]:
            out.append(f"막힌 자리 자체는 열 수 없다: {rel} — 그 안 한 폴더를 연다")
    return out


def opened_deny(p, wt, cfg):
    """열 폴더마다 덮는 항목을 빼고, 그 자리부터 열 폴더까지 마디마다 형제를 하나씩 막는다 — glob 문자 클래스(`[!t]*`)를
    쓰지 않는다(Claude Code가 폴더 전체 막음으로 읽는다). 형제 이름은 리드 체크아웃에서 읽는다. (빼는 항목, 더할 deny).
    열 폴더가 여럿이면 어느 열 폴더 자체이거나 그 조상인 형제는 막지 않고(그 안은 그 폴더의 걸음이 막는다),
    다른 열 폴더 안에 든 열 폴더는 걷지 않는다(바깥이 이긴다)."""
    def within(path, top):
        return (path + os.sep).startswith(top + os.sep)

    opens = []
    for rel in p.get("open") or ():
        rel = rel.strip(os.sep)
        sub = _covering(rel, cfg)
        if not sub or rel == sub[:-3] or ".." in rel.split(os.sep) or not os.path.isdir(os.path.join(p["lead_top"], rel)):
            continue  # open_problems가 막는 값은 deny를 바꾸지 않는다
        opens.append((rel, sub))
    drop, add = set(), []
    for rel, sub in opens:
        drop.add(sub)
        if any(other != rel and within(rel, other) for other, _ in opens):
            continue
        parts = rel.split(os.sep)
        for depth in range(len(sub[:-3].split(os.sep)), len(parts)):
            parent = os.sep.join(parts[:depth])
            for name in sorted(os.listdir(os.path.join(p["lead_top"], parent))):
                if any(within(other, os.path.join(parent, name)) for other, _ in opens):
                    continue
                tail = "/**" if os.path.isdir(os.path.join(p["lead_top"], parent, name)) else ""
                add.append(f"Edit({wt}/{parent}/{name}{tail})")
    return drop, add


def home_deny(p):
    """작업 세션 홈 settings.json의 deny — 리드 체크아웃 경로는 워크트리 경로로 옮긴다(리드 자리를 막던 규칙이 작업 자리를 막게).
    못 읽으면 []."""
    try:
        with open(os.path.join(p["home"], "settings.json"), encoding="utf-8") as f:
            found = (json.load(f).get("permissions") or {}).get("deny") or []
    except (OSError, ValueError, AttributeError):
        return []
    lead, wt = "/" + p["lead_top"], "/" + p["worktree"]
    return [r.replace(lead + "/", wt + "/").replace(lead + ")", wt + ")") for r in found if isinstance(r, str)]


def session_settings(p, cfg):
    """작업 세션 settings: deny만 — 홈 settings deny(리드 경로는 워크트리로 옮김), 리드 체크아웃·세션 기록 자리·플러그인 자리
    (훅을 고쳐 풀 수 없게)·홈 settings.json, 규칙 `src/rules/files.json`의 자리(워크트리 안)·`src/rules/git.json`에서 만든 Bash 앞머리, 질문 창(`AskUserQuestion` —
    PreToolUse 훅이 안 걸려도 막히게). 훅은 넣지 않는다 — 플러그인 훅이 건다(여기 또 넣으면 두 번 돌아 되돌림 횟수가 두 배로 센다)."""
    lead, wt, rec = "/" + p["lead_top"], "/" + p["worktree"], "/" + p["session_dir"]
    deny = home_deny(p)
    deny += [f"Edit({lead}/**)", f"Edit({rec}/**)", f"Edit(/{p['plugin_root']}/**)", f"Edit(/{p['home']}/settings.json)"]
    drop, opened = opened_deny(p, wt, cfg)
    deny += [f"Edit({wt}/{sub})" for sub in rules.files().paths if sub not in drop] + opened
    deny += [f"Edit({wt}/{cfg.rel('carryover')})"]  # 장부는 리드만 쓴다 — 자리가 설정 quest.quests에서 나와 여기서 싣는다
    deny += [f"Bash({c}:*)" for c in rules.git().deny_bash]
    deny += ["AskUserQuestion"]
    return {"permissions": {"deny": list(dict.fromkeys(deny))}}
