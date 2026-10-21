# ContextCue Backend Implementation Plan

> **Status:** 실행 순서와 진행 상태를 관리하는 Backend 작업 문서 (2026-10-21)
> **Current phase:** Phase 1 시작 전
> **Next task:** Phase 1.1 — `tasking/models.py`의 최소 도메인 모델과 모델 검증 테스트 추가

이 문서는 새로운 개발 세션에서도 ContextCue Backend 작업을 안전한 순서로 이어가기 위한 실행 계획이다. 제품 범위는 `docs/PROJECT_PLAN.md`, 모듈과 데이터 경계는 `docs/SYSTEM_ARCHITECTURE.md`, 자동문 행동 기준은 `docs/scenarios/automatic-door.md`를 우선한다. 실제 구현 여부는 항상 코드와 테스트를 다시 확인한다.

## 1. 새 작업 세션에서 먼저 할 일

1. 루트 `AGENTS.md`, `backend/AGENTS.md`, `README.md`, `docs/TEAM_WORKFLOW.md`를 읽는다.
2. 이 문서와 현재 작업할 Phase에 연결된 `/docs` 문서를 읽는다.
3. `git status`와 `git branch --show-current`를 확인한다. 변경 사항을 버리거나 임의로 브랜치를 바꾸지 않는다.
4. 아래 **현재 구현 상태**와 실제 파일·테스트가 일치하는지 확인한다.
5. 완료되지 않은 가장 앞 Phase의 첫 체크박스부터 한 단위만 구현한다.
6. Backend 변경 후 `uv run pytest`와 `uv run ruff check .`를 `backend/`에서 실행한다.
7. 완료한 항목만 체크하고, 결과·제약·다음 작업을 이 문서에 갱신한다. 테스트를 실행하지 않았다면 완료로 표시하지 않는다.

현재 문서 작성 시점의 브랜치는 `docs/generic-task-engine-architecture`다. `main`의 `f43171a`를 병합한 `e78a752`가 로컬에 있으며, 문서 작성 시작 시 원격 기능 브랜치보다 2커밋 앞서 있었다. 이 정보는 스냅샷이므로 다음 세션에서는 Git 상태를 다시 확인해야 한다.

## 2. 현재 구현 상태

### 완료되어 있는 기반

- [x] FastAPI `GET /api/health`와 `POST /api/plan`
- [x] `PlanRequest`/`PlanResponse`, `Profile`, `SceneObject` Pydantic 계약
- [x] 정규화 bbox 범위와 scene object ID 중복 검사
- [x] `DEMO_RULES`와 선택적 `LIVE_NEBIUS` 경로 구분
- [x] 모델이 선택한 object ID의 grounding 및 label/대상 모호성 검사
- [x] 우유 가져오기에서 `can_grasp` 검사
- [x] 자동문 단일 단서에서 `can_press_button`과 `can_extend_arm` 검사 (`f43171a`)
- [x] live provider 실패를 demo 결과로 숨기지 않고 HTTP 502로 반환
- [x] Frontend의 별도 가방 챙기기 로컬 상태 머신과 도움 수준 0–4
- [x] 현재 Backend 회귀 기준: 2026-10-21 문서 정비 후 `uv run pytest` 46개 통과, `uv run ruff check .` 통과

### 아직 구현되지 않은 목표

- [ ] Backend Generic Task Engine
- [ ] 범용 `TaskPlan`, `TaskStep`, `TaskState`, `TaskEvent`, `Evidence`
- [ ] 의미적 target과 관찰된 object binding의 분리
- [ ] 행동별 Trusted Action/Completion Policy
- [ ] 행동 완료 Evidence 판정
- [ ] Backend Prompting Policy와 Task orchestration
- [ ] 구조화된 AI Task Planner와 검증된 Template 선택
- [ ] 신규 Task lifecycle API와 세션 보관
- [ ] Frontend Task Engine 연결
- [ ] 실제 카메라/검출기, ASR, 음성 출력
- [ ] 부분 재계획, 장기 기억, Prompt Fading

### 현재 코드의 중요한 한계

- `app/planner.py`는 `retrieve_object`, `open_door`, `unknown`만 처리하는 단일 단서 planner다.
- 현재 `/api/plan`은 Task Plan이나 행동 결과를 반환하지 않는다.
- 현재 자동문 응답은 버튼 위치 찾기와 누르기 능력을 하나의 보수적 검사로 묶는다. 새 Task Engine에서는 `locate`와 `press`를 별도 단계로 모델링하되 레거시 API 동작을 무심코 변경하지 않는다.
- Frontend 가방 데모의 `next`와 `caregiver_confirm`은 다음 단계로 이동하지만 실제 Evidence를 저장하지 않는다. 화면의 `completed`는 관찰된 실제 완료가 아니다.
- 현재 장면은 `DEMO_SCENE` fixture이며 실제 카메라 인식이 아니다.
- `LIVE_NEBIUS` 호출 코드는 존재하지만 실제 모델 가용성·구조화 출력·지연은 검증되지 않았다.

## 3. 확정된 설계 결정

### 3.1 패키지와 의존 방향

- 새 Backend 기능은 하나의 `app/tasking/` 패키지에 둔다.
- `models.py`는 다른 `tasking` 모듈을 import하지 않는다.
- `engine.py`는 순수 상태 전이만 수행하며 FastAPI, AI provider, 과제명, 카메라를 알지 못한다.
- `service.py`가 planning → verification → engine → prompting 순서를 조정한다.
- Engine에는 `open_door`, `packing_bag` 같은 과제명별 분기를 넣지 않는다.
- 새 과제가 기존 action vocabulary를 조합하면 Engine 변경 없이 TaskPlan 데이터만 추가한다.
- 새로운 행동 의미가 필요할 때는 Engine이 아니라 trusted Action Policy를 확장한다.

### 3.2 unresolved target

- `TargetRef`는 `target_key`, 의미적 `concept`, 제한된 qualifier만 갖는다. 관찰 object ID와 bbox를 넣지 않는다.
- `TargetBinding`은 검증된 `object_id`와 `observation_revision`을 별도로 기록한다.
- 현재 binding은 `TaskState.target_bindings`에 저장한다.
- 물체가 아직 관찰되지 않아도 `TargetRef`는 유효하다. 텍스트·음성으로 찾기를 안내할 수 있다.
- highlight/arrow 또는 `press`, `grasp`, `place_inside` 같은 물리 행동은 유효한 binding 전에는 실행하지 않는다.
- AI가 향후 object ID 후보를 제안하더라도 현재 observation에서 확인된 뒤에만 binding으로 승격한다. 좌표는 언제나 observation에서 조회한다.

### 3.3 trusted completion

- AI/Template TaskPlan은 의미적 `CompletionGoal`만 선언한다.
- Plan은 허용 Evidence source, confidence threshold, 완료 quorum을 정하지 못한다.
- trusted `ActionPolicyRegistry`가 action별 허용 outcome, 필수 capability, binding 요구와 완료 Evidence 규칙을 제공한다.
- `manual_progress`, `cue_issued`, `model_assessment`, 무응답은 물리 행동의 완료 증거가 아니다.
- AI Verification 결과는 contextual assessment이며 관찰 Evidence가 아니다.
- 알 수 없거나 action과 맞지 않는 completion goal은 실행하지 않고 확인/거부한다.

### 3.4 상태와 도움

- Task 진행 상태와 prompt 도움 수준은 독립된 상태 축이다.
- 도움 수준은 명시적 사용자/보호자 요청 또는 신뢰 가능한 difficulty event로만 증가한다. 단순 무응답으로 자동 증가하지 않는다.
- 새 단계 진입 시 그 단계의 초기 도움 수준으로 재설정한다.
- `manual_advance`는 첫 구현에서 단계를 완료하거나 이동시키지 않고 `needs_confirmation`으로 전환한다.
- 마지막 단계까지 trusted completion을 만족해야만 Task가 `completed`가 된다.

### 3.5 Verification 순서

1. Pydantic 구조와 참조 무결성 검사
2. 존재하는 object binding의 ID·observation revision·모호성 검사
3. trusted Action Policy의 명시적 금지·필수 capability·completion 규칙 검사
4. 앞 단계가 통과했고 추가 맥락 판단이 필요한 경우에만 선택적 AI Verification
5. AI 결과 재검증 후 allow/confirm/assist/stop 중 안전한 결과 적용

AI는 앞 단계의 hard rejection을 뒤집거나 새 object ID, bbox, 행동 성공을 생성할 수 없다. unresolved target 자체는 오류가 아니지만, binding이 필수인 행동에서는 `awaiting_target` 또는 `needs_confirmation`으로 처리한다.

## 4. 목표 디렉터리 구조

아래 파일을 한 번에 만들지 않는다. 각 Phase에서 필요한 파일만 추가한다.

```text
backend/
├── IMPLEMENTATION_PLAN.md
├── app/
│   ├── main.py                     # 기존 API 유지
│   ├── schemas.py                  # 기존 /api/plan 공개 계약
│   ├── planner.py                  # 기존 단일 단서 facade
│   ├── tasking/
│   │   ├── __init__.py
│   │   ├── models.py               # Phase 1
│   │   ├── engine.py               # Phase 1
│   │   ├── verification.py         # Phase 2
│   │   ├── prompting.py            # Phase 3
│   │   ├── service.py              # Phase 3
│   │   └── planning.py             # Phase 4
│   └── templates/                  # Phase 3 이후, 검토된 데이터만
│       └── automatic_door.v1.json
└── tests/
    ├── test_api.py
    ├── test_planner.py
    ├── test_task_models.py
    ├── test_task_engine.py
    ├── test_task_verification.py
    ├── test_task_prompting.py
    ├── test_task_service.py
    └── fixtures/
        └── plans/
            ├── automatic_door.json
            └── packing_bag.json
```

실제 카메라 등 복수 perception source가 생기기 전에는 `perception/` 패키지를 만들지 않는다. 새 route와 저장소 파일도 해당 Phase 전에는 추가하지 않는다.

## 5. Phase 의존 관계

```mermaid
flowchart LR
  P0[Phase 0: baseline] --> P1[Phase 1: models + pure engine]
  P1 --> P2[Phase 2: trusted verification]
  P2 --> P3[Phase 3: prompting + service + reviewed fixtures]
  P3 --> P4[Phase 4: AI planner + live validation]
  P3 --> P5[Phase 5: Task API + session]
  P4 --> P5
  P5 --> P6[Phase 6: Frontend + evidence integration]
  P6 --> P7[Phase 7: partial replan + persistence + adaptation]
```

Phase 4의 실제 모델 검증은 계정/네트워크 준비가 필요하므로 Phase 3 이후 병렬 준비할 수 있지만, AI가 만든 계획을 공개 Task API에서 사용하려면 Phase 2의 검증 경계가 먼저 완료되어야 한다.

## 6. Phase 0 — 기존 안전 기준선과 문서 정렬

**상태:** 완료

**목표:** 기존 `/api/plan`을 안전한 회귀 기준으로 보존하고 목표 구조와 현재 구현을 구분한다.

**완료 작업**

- [x] `/api/plan`의 객체 grounding, bbox, 중복 ID 검사 확인
- [x] `f43171a`의 자동문 `can_press_button` + `can_extend_arm` 검사와 테스트 반영
- [x] `DEMO_SCENE`, `DEMO_RULES`, `LIVE_NEBIUS` 용어 구분
- [x] 자동문 대표 시나리오와 가방 Frontend 데모의 역할 구분
- [x] Generic Task Engine 방향 합의
- [x] 단일 `tasking/` 패키지, unresolved target, trusted completion, verification 순서 합의
- [x] 상세 Backend 구현 계획 작성

**관련 파일**

- `app/main.py`
- `app/schemas.py`
- `app/planner.py`
- `tests/test_api.py`
- `tests/test_planner.py`
- `docs/PROJECT_PLAN.md`
- `docs/SYSTEM_ARCHITECTURE.md`

**완료 기준**

- 기존 Backend 회귀 테스트와 lint가 통과한다.
- 목표 기능을 구현 완료로 잘못 표시하지 않는다.
- 다음 작업이 Phase 1.1로 명시되어 있다.

## 7. Phase 1 — 최소 도메인 모델과 순수 Generic Task Engine

**상태:** 미구현 — 바로 다음 Phase

**목표:** AI, API, DB 없이 범용 계획·상태·이벤트·증거 모델과 결정론적인 순수 상태 전이를 구현한다.

**선행 조건**

- Phase 0 완료
- 기존 `/api/plan` 계약을 변경하지 않기로 유지

### Phase 1.1 — 최소 모델

**수정 대상**

- `app/tasking/__init__.py` 신규
- `app/tasking/models.py` 신규
- `tests/test_task_models.py` 신규

**작업**

- [ ] `TargetRef`: 의미적 target만 표현하고 object ID/bbox 필드 금지
- [ ] `TargetBinding`: `target_key`, 검증된 `object_id`, `observation_revision` 분리
- [ ] `CompletionGoal`: outcome과 target key만 표현하고 Evidence source 정책 금지
- [ ] `TaskStep`: step ID, action, target key, completion goal, 최대 도움 수준
- [ ] `TaskPlan`: schema version, plan ID, goal, targets, 순서가 있는 steps
- [ ] `Evidence`: source, claim/outcome, target/object 참조, supports/contradicts/inconclusive
- [ ] `TaskEvent`: pause/resume/stop/refusal/more-help/help/manual-advance/cue-issued/target-bound/evidence-received
- [ ] `StepState`와 `TaskState`: 단계 상태, 현재 단계, 독립 help level, binding, evidence
- [ ] Pydantic model은 mutable default를 공유하지 않고 알 수 없는 제어 필드를 거부

**테스트 및 완료 기준**

- [ ] object ID가 없는 unresolved `TargetRef`가 유효하다.
- [ ] `TargetRef`에 bbox/object ID를 직접 넣으면 거부한다.
- [ ] 중복 target/step ID와 존재하지 않는 target key 참조를 거부한다.
- [ ] Plan이 allowed Evidence sources나 confidence threshold를 지정할 수 없다.
- [ ] 모델 round-trip과 기본값 독립성을 검증한다.

### Phase 1.2 — 두 과제 fixture

**수정 대상**

- `tests/fixtures/plans/automatic_door.json` 신규
- `tests/fixtures/plans/packing_bag.json` 신규
- `tests/test_task_models.py`

**작업**

- [ ] 자동문을 `locate_button → press_button → confirm_open → pass_through`로 표현
- [ ] 가방 챙기기를 `locate_bag → locate_bottle → place_bottle → verify_items`로 표현
- [ ] 두 fixture 모두 특정 관찰 object ID 없이 semantic target으로 시작
- [ ] `complete` pseudo-step을 만들지 않고 마지막 행동의 trusted completion으로 Task 종료

**테스트 및 완료 기준**

- [ ] 두 JSON이 동일한 `TaskPlan` 모델로 검증된다.
- [ ] fixture 안에 bbox나 관찰 object ID가 없다.
- [ ] 시나리오별 Python 실행 파일이 없다.

### Phase 1.3 — 제어 상태 전이

**수정 대상**

- `app/tasking/engine.py` 신규
- `tests/test_task_engine.py` 신규

**작업**

- [ ] 초기 `TaskState` 생성
- [ ] pause/resume, stop, refusal 처리
- [ ] 명시적인 more-help/help 요청 처리
- [ ] 단계와 help level을 독립적으로 관리
- [ ] 무응답으로 상태가 변하지 않도록 보장
- [ ] `manual_advance`는 이동하지 않고 `needs_confirmation`으로 전환
- [ ] invalid transition은 상태를 손상시키지 않는 명확한 결과로 반환

**테스트 및 완료 기준**

- [ ] pause 중 진행 이벤트가 차단되고 resume 후 재개된다.
- [ ] stop/refusal 후 terminal 상태에서 진행하지 않는다.
- [ ] more-help 이벤트에서만 help level이 증가하고 상한을 넘지 않는다.
- [ ] 단계 번호 변경 없이 help level만 변할 수 있다.
- [ ] 무응답을 나타내는 이벤트/호출 부재는 실패나 도움 증가가 아니다.

### Phase 1.4 — binding, Evidence와 완료 전이

**수정 대상**

- `app/tasking/engine.py`
- `tests/test_task_engine.py`

**작업**

- [ ] 검증 완료된 내부 `target_bound` 이벤트로만 `TaskState.target_bindings` 갱신
- [ ] Evidence를 append-only 기록으로 상태에 추가
- [ ] Engine이 action 의미를 하드코딩하지 않도록 작은 `CompletionEvaluator` callable/protocol 주입
- [ ] trusted evaluator가 승인한 Evidence에서만 단계 완료 및 다음 단계 이동
- [ ] 다음 단계 진입 시 help level 초기화
- [ ] 모든 단계가 trusted completion을 충족한 경우에만 Task 완료

**테스트 및 완료 기준**

- [ ] unresolved target을 포함한 계획을 시작할 수 있다.
- [ ] `cue_issued`, `manual_progress`, `model_assessment`, inconclusive Evidence가 완료시키지 않는다.
- [ ] contradictory Evidence는 자동 완료하지 않고 확인 상태로 전환한다.
- [ ] trusted camera/caregiver Evidence는 테스트 evaluator를 통해 단계를 완료할 수 있다.
- [ ] 자동문과 가방 fixture가 같은 Engine과 evaluator 인터페이스를 사용한다.
- [ ] Engine에 task 이름별 분기가 없다.

### Phase 1 전체 완료 게이트

- [ ] `app/main.py`, `app/schemas.py`, `app/planner.py`, Frontend를 변경하지 않았다.
- [ ] `PlanPatch`, AI, 신규 API, DB, production Verification Agent를 추가하지 않았다.
- [ ] `uv run pytest` 통과
- [ ] `uv run ruff check .` 통과
- [ ] 실제 테스트 수와 결과를 이 문서의 진행 상태에 기록

## 8. Phase 2 — Trusted Action/Completion Policy와 결정론적 Verification

**상태:** 미구현

**목표:** AI 계획이나 Evidence가 명시적 안전 제약과 완료 규칙을 우회하지 못하게 한다.

**선행 조건**

- Phase 1 완료
- 최소 action vocabulary 검토

**수정 대상**

- `app/tasking/verification.py` 신규
- `app/tasking/models.py`
- `app/tasking/engine.py`의 evaluator 연결부
- `tests/test_task_verification.py` 신규
- 필요 시 `tests/test_task_engine.py`

**작업 순서**

- [ ] `ActionPolicy`와 작은 registry 정의
- [ ] 초기 generic action: `locate`, `press`, `observe_state`, `traverse`, `place_inside`
- [ ] action별 target cardinality와 binding 요구 정의
- [ ] action별 필수 capability와 false/unknown 처리 정의
- [ ] action별 허용 `CompletionGoal`과 Evidence source 정의
- [ ] Plan 구조/참조 검증 → binding 검증 → capability/hard constraint 검사 순서 구현
- [ ] 기존 `Profile`을 내부 capability fact로 변환하는 adapter 구현
- [ ] unsupported action/outcome/capability key를 안전하게 거부
- [ ] AI Verification은 아직 구현하지 않고 `context_review_required` 같은 결과만 표현

**테스트 및 완료 기준**

- [ ] `locate`는 unresolved target을 허용하고 누르기 능력을 요구하지 않는다.
- [ ] `press`는 binding 및 `can_press_button`/`can_extend_arm`을 요구한다.
- [ ] false capability는 assistance/stop, unknown은 confirmation으로 구분된다.
- [ ] AI/Plan이 manual 또는 model Evidence를 완료 source로 만들 수 없다.
- [ ] stale/unknown object binding이 거부되고 좌표는 생성되지 않는다.
- [ ] 구조 또는 hard constraint 실패 시 AI 호출 지점에 도달하지 않는다.
- [ ] 기존 `/api/plan` 46개 회귀 테스트를 유지한다.

## 9. Phase 3 — Prompting Policy, Service orchestration, 검토된 fixture/template

**상태:** 미구현

**목표:** 검증된 단계에 대해 한 번에 하나의 단서를 고르고, 외부 부작용 없이 전체 실행 순서를 조정한다.

**선행 조건**

- Phase 2 완료

**수정 대상**

- `app/tasking/prompting.py` 신규
- `app/tasking/service.py` 신규
- `app/templates/automatic_door.v1.json` 선택적 신규
- `tests/test_task_prompting.py` 신규
- `tests/test_task_service.py` 신규

**작업 순서**

- [ ] help level과 사용자 guidance 선호를 입력으로 받는 순수 Prompting Policy 구현
- [ ] unresolved target에는 좌표 기반 cue를 생성하지 않음
- [ ] bound target cue도 object ID만 전달하고 bbox는 observation lookup에서 가져오게 함
- [ ] cue 발행과 행동 완료를 별도 이벤트로 기록
- [ ] Task Service가 verification → engine → prompting 순서를 조정
- [ ] step 진입과 context 변경에서 재검증하도록 orchestration 정의
- [ ] 자동문 fixture를 검토한 뒤 production template 승격 여부 결정
- [ ] Template 사용 시 source/version을 명시

**테스트 및 완료 기준**

- [ ] 한 번에 cue 하나만 반환한다.
- [ ] 무응답만으로 help level을 올리지 않는다.
- [ ] cue 발행이 step completion을 만들지 않는다.
- [ ] invalid/unbound target에 highlight bbox를 반환하지 않는다.
- [ ] Task Service 테스트는 AI, 네트워크, DB 없이 실행된다.

## 10. Phase 4 — 구조화된 AI Task Planner와 실제 모델 검증

**상태:** 미구현

**목표:** 목표·프로필·관찰을 바탕으로 TaskPlan 제안을 생성하되 trusted verification 밖에서는 실행하지 않는다.

**선행 조건**

- Phase 2 완료
- Phase 3의 service 경계 확정
- 실제 Nebius 계정에서 사용할 모델과 endpoint 확인 가능

**수정 대상**

- `app/tasking/planning.py` 신규
- `app/planner.py`는 호환 facade로 필요한 만큼만 수정
- `tests/test_task_planning.py` 신규
- `tests/test_planner.py` 회귀 유지
- `.env.example`은 새 설정이 실제로 필요할 때만 수정

**작업 순서**

- [ ] Planner 입력에서 transcript를 untrusted data로 취급
- [ ] AI 출력 schema를 `TaskPlan` 제안으로 제한
- [ ] semantic `TargetRef`와 unresolved target을 지원
- [ ] AI가 bbox와 완료 Evidence를 생성하지 못하도록 출력 계약 제한
- [ ] 잘못된 JSON, unknown action, 허위 candidate object ID 처리
- [ ] 검증된 Template 선택과 AI 생성 source를 명시적으로 구분
- [ ] live 호출 실패 시 `DEMO_RULES`로 몰래 fallback하지 않음
- [ ] 실제 Nebius/NVIDIA 호출로 모델 ID, JSON 안정성, latency 확인

**테스트 및 완료 기준**

- [ ] mock provider로 정상/잘못된 JSON/timeout/unknown ID 경로 검증
- [ ] AI 제안은 Phase 2 verification을 통과하기 전 Engine에 들어가지 않는다.
- [ ] AI가 completion policy를 완화할 수 없다.
- [ ] 실제 live 검증을 했다면 재현 가능한 비밀정보 없는 결과를 기록한다.
- [ ] live 검증을 하지 않았다면 `LIVE_NEBIUS` 완료로 표시하지 않는다.

## 11. Phase 5 — Task lifecycle API와 세션 경계

**상태:** 미구현

**목표:** 기존 `/api/plan`을 유지하면서 Generic Task 기능을 별도 versioned API로 노출한다.

**선행 조건**

- Phase 3 완료
- AI 계획을 공개 경로에 쓸 경우 Phase 4 완료
- 세션 저장 방식 결정

**예상 수정 대상**

- `app/main.py` 또는 별도 route 모듈
- `app/schemas.py` 또는 합의된 Task API schema 파일
- `app/tasking/service.py`
- 신규 API 계약 테스트
- 공개 계약 변경 시 `frontend/src/types.ts`

**작업 순서**

- [ ] in-memory server session과 재검증 가능한 stateless state 중 초기 방식을 결정
- [ ] task 생성/조회/event 입력 endpoint 계약 확정
- [ ] event 중복·순서 오류를 다룰 state version 규칙 결정
- [ ] 잘못된 event와 stale observation에 안전한 응답 정의
- [ ] `/api/plan` 계약과 status 값을 변경하지 않음
- [ ] 새 공개 필드를 Backend/Frontend 타입과 테스트에서 함께 갱신

**테스트 및 완료 기준**

- [ ] 레거시 `/api/plan` 요청·응답이 기존과 호환된다.
- [ ] Task API에서 pause/resume/stop/help/evidence 정상·오류 경로가 검증된다.
- [ ] cue/manual input만으로 completed 응답이 나오지 않는다.
- [ ] 프로세스 재시작 또는 다중 worker 한계를 문서화한다.

## 12. Phase 6 — Frontend 및 Observation/Evidence 연결

**상태:** 미구현

**목표:** 자동문 대표 시나리오와 가방 교차 시나리오를 Backend Engine에 연결한다.

**선행 조건**

- Phase 5 완료
- Frontend 담당자와 공유 계약 협의

**예상 수정 대상**

- Backend Task API/adapter 및 테스트
- `frontend/src/types.ts`
- `frontend/src/packing/`와 관련 components
- 자동문 UI/scene 관련 파일
- 필요할 때만 observation adapter 모듈

**작업 순서**

- [ ] Frontend `next`를 성공이 아닌 manual advance 요청으로 전송
- [ ] caregiver 확인에 step, claim, target, source를 포함
- [ ] `completed`와 `needs_confirmation`을 UI에서 구분
- [ ] `DEMO_SCENE` fixture와 실제 perception source를 명확히 표시
- [ ] 자동문 장면에 문 상태와 통과 확인에 필요한 합성 관찰 추가
- [ ] 사용자 A/B의 capability 차이를 E2E로 검증

**테스트 및 완료 기준**

- [ ] Backend pytest/Ruff 통과
- [ ] Frontend typecheck/build 통과
- [ ] 정상·불확실·불가능·거부·중단 경로 확인
- [ ] 자동문과 가방이 동일 Backend Engine을 사용한다.
- [ ] manual QA와 실제 카메라 검증 여부를 별도로 기록한다.

## 13. Phase 7 — 후순위 확장

**상태:** 보류

다음 항목은 Phase 1–6의 계약과 측정 결과가 안정된 뒤 별도 작업으로 진행한다.

- [ ] `PlanPatch`와 현재 단계 이후 suffix 부분 재계획
- [ ] 완료 이력과 Evidence를 보존하는 plan revision 규칙
- [ ] durable persistence 또는 DB
- [ ] 실제 perception/ASR/audio TTS adapter
- [ ] 선택적 독립 Verification Agent
- [ ] 장기 Memory와 증거 기반 Prompt Fading
- [ ] 복수 worker, concurrency, event idempotency 강화

각 항목은 별도 설계·위험 검토 없이 앞 Phase에 끼워 넣지 않는다.

## 14. 호환성 및 안전 체크리스트

모든 Phase에서 다음을 유지한다.

- [ ] 기존 `/api/plan` 변경 시 `app/schemas.py`, `frontend/src/types.ts`, 호출부와 계약 테스트를 같은 변경 단위로 갱신한다.
- [ ] bbox는 검증된 observation에서만 반환한다.
- [ ] AI가 임의 object ID, bbox, 행동 성공을 만들지 못한다.
- [ ] `false`와 `unknown` capability를 `true`로 취급하지 않는다.
- [ ] locate 같은 인지적 단계와 press/place 같은 물리적 단계를 분리한다.
- [ ] cue 발행, manual progress, Evidence, 실제 완료를 각각 기록한다.
- [ ] `DEMO_SCENE`, `DEMO_RULES`, `LIVE_NEBIUS`를 구분한다.
- [ ] live provider 오류를 demo 성공처럼 표시하지 않는다.
- [ ] 합성 프로필·장면과 합의된 성인 시연만 사용한다.
- [ ] API key, 실제 장애 기록, 학생 영상, private identifier를 커밋하거나 로그에 남기지 않는다.

## 15. 아직 확정하지 않은 사항

다음은 해당 Phase에서 근거와 테스트를 바탕으로 결정한다.

1. 초기 action vocabulary의 최종 이름과 세부 parameter 형식
2. caregiver report와 camera Evidence의 충돌 및 confidence 처리
3. 실제 target binding의 freshness/추적 기준
4. Task API 세션 저장 방식과 state version/idempotency 계약
5. AI context verification 호출 기준과 latency budget
6. Template 검토·versioning·승격 절차
7. 실제 입력 장치, 비접촉 거부/도움 UX
8. 장기 기억과 Prompt Fading에 필요한 반복 Evidence 기준

미결 사항을 구현 편의로 임의 확정하지 않는다. 필요한 Phase에서 선택지, 근거, 테스트 결과를 문서화한다.

## 16. Phase 완료 시 인수인계 형식

각 작업 종료 시 이 문서에 다음을 남긴다.

```text
완료한 체크박스:
변경 파일:
실행한 검사와 실제 결과:
DEMO_SCENE / DEMO_RULES / LIVE_NEBIUS 여부:
알려진 제한 또는 미결 결정:
바로 다음 작업:
```

체크박스는 코드 존재만으로 완료 처리하지 않는다. 해당 Phase의 테스트 및 완료 기준을 실제로 충족했을 때만 `[x]`로 바꾼다.
