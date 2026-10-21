# ContextCue — Documentation Index

문서가 같은 내용을 서로 다르게 정의하지 않도록 **책임을 분리**한다.

| 문서 | 질문/책임 | 관리 원칙 |
|---|---|---|
| [PROJECT_PLAN.md](PROJECT_PLAN.md) | 왜 만들며, 누구를 위해, 이번 MVP에서 무엇을 끝낼 것인가? | 제품 목표·요구사항·수용 기준의 상위 기준 |
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | 이를 어떤 모듈·상태·데이터 계약으로 구현할 것인가? | 실제 코드/목표 구조의 차이 표기 |
| [scenarios/automatic-door.md](scenarios/automatic-door.md) | 버튼식 자동문에서 어떤 행동·예외·증거가 필요한가? | 대표 MVP의 행동 수준 규칙 |
| [qa/frontend-manual-checklist.md](qa/frontend-manual-checklist.md) | 어떤 브라우저/접근성 동작을 어떻게 검증할 것인가? | 계획과 실제 실행 결과를 구분 |
| [TEAM_WORKFLOW.md](TEAM_WORKFLOW.md) | 2인이 Git/작업 소유권/공유 API를 어떻게 협의할 것인가? | 현재 main-first 원칙 유지 |

## 일관성 원칙

1. **프로젝트 범위·우선순위:** PROJECT_PLAN.md.
2. **모듈 경계·설계상의 상태:** SYSTEM_ARCHITECTURE.md.
3. **시나리오별 기대 행동:** scenarios 디렉터리.
4. **현재 실행 가능한 API·타입:** 실제 `backend/app/schemas.py`, `frontend/src/types.ts`와 테스트. 설계안과 다르면 구현이 이미 맞다고 가정하지 말고 차이를 이슈로 남긴다.
5. **개발 에이전트 지침:** 루트 `AGENTS.md`와 경로별 `AGENTS.md`. 본문 요구사항을 중복 복사하지 않고 관련 문서만 참조한다.
6. **프로젝트 첫 화면·실행법:** [루트 README](../README.md).

기존의 별도 초기 아이디어 노트·초기 아키텍처 초안에서 현재 유효한 내용은 위 두 핵심 문서로 정리했다. 현재 대표 MVP는 **자동문**이며, 가방 챙기기는 별도의 Frontend 데모다.

날짜와 상태가 표시된 문서의 완료 표시는 해당 시점의 스냅샷이다. 최신 현황은 코드/테스트/CI와 함께 확인한다.
