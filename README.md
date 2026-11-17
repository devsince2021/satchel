# satchel

Claude Code 에이전트 작업 흐름을 플러그인으로 모은 장터다. `plugins/` 아래 폴더 하나가 설치 단위다.

## 플러그인

| 이름 | 판 | 무엇 |
| --- | --- | --- |
| [scroll](plugins/scroll/README.md) | 0.12.0 | 리드 세션이 작업 하나를 작업 세션에 맡기고, 작업 세션이 설계 → 검토 → TDD 구현 → 검토 → 반영 → 마무리를 스스로 돈 뒤 리드가 합치는 퀘스트 흐름(`/quest`) |

## 설치

```
/plugin marketplace add <이 저장소 주소 또는 로컬 경로>
/plugin install scroll@satchel
```

필요한 것과 설정은 각 플러그인 README에 있다.

## 라이선스

MIT — [`LICENSE`](LICENSE).
