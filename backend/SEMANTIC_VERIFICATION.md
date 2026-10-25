# Phase 4 F1 — 실행 전 의미 검증 경계

2026-10-22. 기존 E4 baseline의 `d11` 2회·`h05` 1회 실패를 대상으로 구현했다.
기존 Engine, TaskPlan 모델, Action Policy 레지스트리와 공개 API는 유지한다.
후속으로 `request_review.py`의 제한된 영어 요청 문법 adapter와
`planning.generate_reviewed_plan`을 실제 Nebius 경로에 연결했다. 최신 실측은
`EVALUATION_PLAN.md` 12장과 이 문서 마지막 절을 따른다.

## 신뢰의 출처

`goal` 문자열은 요청 범위를 식별할 뿐 안전 승인이나 완전한 의도 해석이 아니다.
모델이 고른 action·target이나 “안전하다”는 자체 평가에서 승인 조건을 만들지 않는다.
서버의 독립적인 요청 검토자가 원래 발화, 목표, 대상/수신자, 거부·위험을 확인한 후
`SemanticReview`와 `SemanticIntent`를 제공해야 한다. 현재 내부 production adapter는
완전히 해석한 제한된 요청만 검토하며, 외부 인증/검토 UI와 범용 자유문장 해석기는
**미구현**이다. 검토 가능한 입력이 없으면
`semantic_review_required`로 보류하며, 단어 blacklist나 goal 이름만으로 자동 승인하지 않는다.

`review_request()`는 검토 결과를 요청에 묶는 생성 helper이지 자연어 판별기가 아니다.
임의의 goal/발화를 `ready`로 바꾸는 어댑터로 사용하면 안 된다. 검토의 진실성은
trusted backend dependency의 책임이다. SHA-256 fingerprint와 review ID는
인증·전자서명·실제 안전 증명이 아니다. 클라이언트/모델 JSON을 이 객체로
deserialize하는 경로를 열지 않았다.

| 독립 검토 상태 | 실행 경계의 결과 |
|---|---|
| 검토 없음 / 원문·scope 변경 / 잘못된 검토 | confirm, 모델 호출 및 실행 진입 차단 |
| unsupported / ambiguous / unknown | confirm; 지원 action으로 대체하지 않음 |
| unsafe / refused | stop; 최초 locate도 실행 승인하지 않음 |
| ready + 검토된 intent | 전체 계획의 목표·action·target 의미 검증 후 기존 물리 검증 진행 |

## 검증하는 계약

`SemanticReview`는 task ID, plan ID, goal, 발화가 포함된 fingerprint와 검토 상태를
보관하는 backend 전용 불변 객체다. `SemanticIntent`의 target·operation 역시
불변 구조이며 모델 출력 schema에 포함되지 않는다. 서로 다른 발화·task·plan의
검토를 생성/실행에 재사용할 수 없다. 발화가 바뀌면 새로운 독립 검토가 필요하다.
이후 Service 호출의 최신 context/review 선택은 trusted caller의 책임이며
서버 세션·승인 이력 저장은 이번 작업에 추가하지 않았다.

- target은 검토된 의미 역할·concept·qualifier와 일치해야 한다. 다른 대상,
  중복 의미 역할, 꾸며낸 색상, 미사용 추가 target을 승인하지 않는다.
- 검토된 concept catalog는 control / passage / item / container 역할을 갖는다.
  `press(scissors)`, `traverse(paper)`, `place_inside(paper, scissors)`는
  검토 계약 자체로 선언할 수 없다. 모르는 concept는 검토 후 `locate`할 수 있지만
  physical action에 쓰려면 catalog의 의미 역할을 별도로 검토·추가해야 한다.
  이름에 `button`이 들어간다는 이유만으로 control로 인정하지 않는다.
- 전체 계획의 non-locate action·completion outcome·ordered target roles가
  검토된 요구 결과 및 순서와 같아야 한다. 누락·추가·대체·역순을 보류한다.
  명시적으로 요구한 locate는 해당 역할의 사용 전에 있어야 한다.
  추가 locate는 검토된 대상에 한해 한 번 허용하며 첫 단계는 locate다.
  step ID나 문장·전체 단계 수를 fixture와 일치시키는 검사는 아니다.
- 검토된 desired effect는 완료 증거가 아니다. 의미 승인은 binding·capability·
  reachability·상태 관찰·Evidence/완료 정책을 만들거나 완화하지 않는다.

예를 들어 “수건을 바구니에 넣고 들어 있는지 확인”을 독립 검토한 intent는
`item=towel`, `container=basket`, 각 대상 찾기, `placed_inside(item,container)`와
`items_inside(item,container)`를 요구한다. 모델이 수건 대신 책을 선택하거나
바구니 안 확인 대신 열림 확인을 제안하면 보류한다. 같은 범용 규칙이 문/가방/
책/엘리베이터 버튼에 적용되며 Engine에 과제별 분기를 추가하지 않았다.

## 호출 경계와 책임

```mermaid
flowchart LR
  R[원래 사용자 요청] --> I[독립 backend 요청 검토]
  I --> G[모델 호출 전 review scope 검사]
  G --> P[AI TaskPlan 제안]
  P --> V[구조·정책 vocabulary와 전체 의미 검증]
  V --> S[시작 직전 현재 review 재검증]
  S --> T[Service: 의미 검증 → Action Policy → Engine]
  T --> C[Prompting: 의미·정책 재검증 후 cue]
```

- `planning.py`: 검토 없이 provider를 호출하지 않는다. 생성·Template 선택에
  같은 의미 계약을 적용하고, 시작 때 proposal의 cached allow를 신뢰하지 않는다.
- `semantics.py`: 독립 검토 scope, 요청 상태, 전체 계획/역할/요구 결과를 소유한다.
- `VerificationContext.semantic_review`: backend 전용 검토 dependency를 전달한다.
  기존 `verify_step`과 `ACTION_POLICIES`의 구조·능력·binding·물리/Evidence 정책은
  의미 판별기나 자유문장 parser로 바꾸지 않았다.
- `service.py`: polling, 도움 요청에 따른 cue, binding·Evidence 수용 전에
  전체 의미를 재검증한다. 승인 누락·철회·계획 변조 시 진행/단서를 차단한다.
  stop/refusal/help 같은 기존 안전 제어는 계속 사용할 수 있다.
- `prompting.py`: 독립 직접 호출도 검토 없이 cue를 만들지 않는다. 따라서
  synthetic feasibility=true로 Action Policy가 allow해도 의미 부적합 cue는 차단한다.
- `engine.py`: 변경 없음. 순수 상태 전이·Evidence 완료의 기존 책임을 유지한다.

## 검증과 호환성

아래는 첫 경계 도입 시점의 559개 테스트/mock 기록이며, 후속 adapter의 최신
검증·live 수치는 마지막 절에 별도로 기록한다.

- F1에서 실제 생성됐던 d11 두 계획과 h05 두 번째 계획은 저장된 원문을
  mock으로 재생했다. 독립 검토를 각각 unsupported/unsafe로 주고 모델 호출
  0회, `start_planned_task` Service 미진입, 직접 cue 및 내부 later-step cue
  미생성을 확인했다. 이 결과는 **새 LIVE_NEBIUS 성공이 아니다**.
- 신규 41개 의미 회귀: 미지원 끓이기/열쇠 열기, 모호한 수신자, 연기 나는 버튼,
  거부, action-object 부적합, 역할 역전·결과 누락·추가 행동, 검토 재사용·철회·
  자기 승인·변조, 정상 수건→바구니·엘리베이터·단일 locate를 포함한다.
- E4 역사 runner의 별도 preflight 테스트 1개를 추가했다. 최종 전체
  `uv run pytest`: **559 passed** (기존 517 + 42), `uv run ruff check .` 통과.
  기존 Starlette deprecation 1건과 uv의 `SSL_CERT_DIR` 경고는 남는다.
- 모든 기존 Planning/Service/Prompting 정상 fixture는 **명시적으로 검토한
  합성 intent**를 제공하도록 갱신했다. 기존처럼 review 없이 호출하면 확인으로
  보류하는 것이 의도한 내부 계약 변경이다. 공개 HTTP API/schema·Frontend는 그대로다.
- `scripts/verify_phase4.py`는 원래 두 고정 합성 과제만 명시적으로 검토해 사용한다.
  이번에는 이 script의 실제 모델 호출을 실행하지 않았다.
- 과거 `scripts/evaluate_e4.py --live`에는 독립 요청 검토 adapter가 없으므로
  preflight에서 종료한다. 평가 expected 조건으로 요청을 자동 승인하거나,
  미호출 결과를 LIVE_NEBIUS로 저장하지 않는다. 향후 새로운 평가에는 독립 검토
  adapter/ledger를 먼저 준비해야 한다. mock 변조 control만 명시적 합성 review로 유지한다.
- 동결된 `cases.json`, baseline README/rubric, live/mock 원본·집계·agent-review는
  수정하지 않았다. E4 baseline은 `evaluated_needs_improvement`로 유지한다.
  F2–F5의 전체 해결, E4 사람 채점·수정 후 live 재평가를 주장하지 않는다.

Phase 5 API·세션·검토 UI, 새 LLM 의미 판별기, prompt 튜닝, dependencies 변경,
commit/push는 수행하지 않았다.

## Production 요청 검토 adapter 연결 및 후속 평가

- `ControlledRequestReviewer`는 원래 goal과 transcript만 받는 순수 서버 모듈이다.
  case ID, 장면, 능력, 모델 제안, 평가 expected label을 읽지 않는다. goal과 발화를
  **각각** 의미 계약으로 해석해 일치할 때만 ready로 승인한다. 단어 목록에 위험이
  없다는 이유만으로 승인하지 않는다. 전체 문장이 지원 문법과 맞아야 한다.
- 범위: 제한된 영어 locate-only, control 찾기/누르기, 물체→용기 넣기/내부 확인,
  개방 확인/통과 및 제어 버튼을 포함한 문 통과. 관찰되지 않은 대상도 의미적으로
  검토할 수 있지만 물리 승인/binding은 만들지 않는다. 알려진 부정·위험 표현은
  추가 veto로만 쓰고, 미인식 문장·추가 명령·goal 충돌은 확인으로 보류한다.
- `generate_reviewed_plan(request, provider)`는 adapter 검토 후 기존 `generate_plan`
  전체 검증을 호출한다. 요청 보류는 `ReviewedPlanningResult`에 이유와 상태를
  반환하고 model을 호출하지 않는다. 모델/JSON/계획 오류는 기존 `PlanningError`로
  유지한다. 실행은 반환 review를 포함한 context로 `start_planned_task`에 전달한다.
  고정 두 과제의 `verify_phase4.py`도 수동 합성 승인 대신 이 경로를 사용한다.
- 일반적인 자유문장, 한국어의 긍정 요청, 인용문 안의 명령 분리, 모든 안전 상황을
  지원하는 parser가 아니다. `d06` 도달 불가 설명과 `d12` 인용 주입의 정상 분류
  입력은 보류돼 adapter coverage가 **36/40**이었다. 현장 안전 인증이나 임상적
  의미 이해를 주장하지 않는다. 지원 문법을 확장할 때는 독립 회귀·새 평가가 필요하다.
- 후속 실측: 기존 E4 18개 + 새 12개, 각 2회 **60 시도**. 실제 Nebius **36회**,
  deterministic review **24회**를 구분했다. 정상 입력 **22/40 수용**, 보류 필요
  **20/20 차단**, 모델의 계약 불일치 제안 **13/13 차단**. 별도 mock replay에서
  원래 score-0 출력 **6/6 차단**, 적절한 정상 계획 **13/15 유지**, 악성 변조
  **8/8 차단**·positive control **1/1 수용**. 모드별 분모를 혼합하지 않는다.
- 최종 `uv run pytest` **582 passed**, `uv run ruff check .` 통과. 기존 자료는
  hash 검증으로 보존했다. 새 버전은 `evaluations/e4_f1_v2/`이며 기존 E4 v1
  runner는 역사 보존용으로 차단된 채 유지한다. 재현 명령은 새 버전 README 참조.
- F1의 기존 실행 우회와 지원 문법 경계는 구현·검증했지만, 정상 계획 유용성과
  범용 자연어 지원까지 해결한 것은 아니다. E4는 `evaluated_needs_improvement`로
  유지한다. 공개 Task API/세션·다른 Phase·commit/push는 진행하지 않았다.

## F2/F3 — 요청별 생성 제약과 안전한 표기 정규화 (2026-10-23)

기존 독립 검토·전체 의미 검증의 승인 조건은 유지한다. 모델의 제안에서 정답을
만들거나 평가 expected label을 production 코드로 읽지 않는다.

1. `generate_plan`은 현재 요청의 독립 review를 검사한 뒤 intent에서 요청별
   JSON schema와 prompt 계약을 만든다. canonical concept/qualifier·역할 key,
   허용 action/outcome/ordered target keys, 대상/단계 수를 제한한다. 최소한의
   locate와 모든 필수 결과를 요구하고 추가 physical effect는 허용하지 않는다.
   `{}` 응답 분기는 유지한다. 단계 순서·대상 참조 무결성의 최종 보장은 계속
   로컬 검증의 책임이다.
2. provider가 반환한 strict JSON을 `TaskPlan`으로 검증한다. 미선언/중복 참조,
   모델이 만든 ID·좌표·완료 정책은 이 단계에서 거부하며 복구하지 않는다.
3. `normalization.normalize_proposal`은 복사본의 concept/qualifier 표기만 바꾼다.
   변환 후 identity가 독립 intent의 정확한 identity인 경우만 허용한다.
   casefold·공백/하이픈→underscore, 닫힌 `door_opening_button` alias,
   명시적인 red/blue/green mug의 색상 분리만 지원한다. 생략 색상 추정,
   `cup→mug`, 일반 `button→door_open_button`은 허용하지 않는다.
   상충 색상·정규화 후 중복 identity는 `normalization_conflict`로 보류한다.
4. 변경 전후 concept/qualifier를 불변 `PlanProposal.normalizations`로 기록하고,
   기존 `_validate_plan`의 ActionPolicy vocabulary·역할·전체 의미 검증을 적용한다.
   시작/Service/cue에서도 기존 strict 검증을 반복한다. 이후 계획 변조를 정규화로
   복구하지 않으며 Template에도 이 정규화를 자동 적용하지 않는다.

정규화는 target key·참조·step·action·outcome·순서·review를 바꾸지 않는다.
관찰을 변환하거나 관찰 개수를 근거로 identity를 추측하지 않는다. 누락/모호한
객체는 locate를 제안할 수 있어도 physical step에서 binding 확인이 필요하며,
색상 alias를 허용한 뒤에도 중복 관찰·stale binding은 계속 차단한다.
차단/unknown 능력과 실제 reachability 역시 독립적인 ActionPolicy의 책임이다.

실측 전후 정상 **28/48→44/48**, 보류 요청 **28/28 차단 유지**다. 후자는
독립 review 결과이며 모델의 위험 거부율이 아니다. 동일 원문 Mock replay는
유효한 alias 2건만 회복했고, 별도 정상 대조군 **1/5→5/5**·부적절 계획
**16/16 차단 유지**를 확인했다. 새 회귀 26개를 포함해 pytest **609 passed**,
Ruff 통과. 자료·분모·범위/지연 한계는 `EVALUATION_PLAN.md` 11장 참조.
이 변화는 F1의 자유문장 coverage·F4/F5·Phase 5를 확장하지 않는다.

## F4/F5 — 보류 진단·대상 표현의 후속 경계 (2026-10-23)

- 모델은 TaskPlan 대신 닫힌 `status=abstain`/reason_code 객체를 선언할 수 있다.
  이 분기는 strict JSON·추가 필드/중복 key 검사 후에만 인정하고, backend scope와
  provenance를 담은 불변 `PlanAbstention`으로 구분한다. 모델 선언은 독립 review나
  관찰 사실이 아니며 `safety_concern`/`user_refusal`로 trusted 판정을 덮어쓰지 않는다.
  결과는 confirm/no-proposal이며 Service/Engine을 생성하지 않는다.
- legacy `{}`는 `model_no_plan`으로 구분하지만 사유/의도는 알 수 없다. 잘못된
  선언·JSON·참조와 transport 실패는 계속 오류다. 독립 unsafe/refused 요청은
  호출 전 stop을 유지한다. 저수준 `PlanningAbstained`는 `PlanningError`의 하위
  타입이므로 기존 fail-closed 처리도 유지한다.
- Prompting은 의미·정책 gate 후에만 닫힌 한국어 concept/qualifier 사전을 사용한다.
  알려진 이름·속성을 안내하고, 모르는 설명은 raw 모델 문자열을 출력하거나
  속성을 생략하지 않고 neutral assistance cue로 전환한다. 이 표현 fallback은
  행동 승인·관찰/binding·Evidence·완료·Engine 상태를 만들지 않는다.
- 실제 모델은 선언을 통해 스스로 계획을 보류할 수 있지만 실행 승인이나
  정책 완화는 할 수 없다. 이번 typed 응답 계약과 안내 수정은 기존 F1의
  지원 문법 coverage나 공개 API를 확장하지 않는다. 회귀/실측의 정확한 분모와
  남은 사유 정확성·사용자 이해도 검증은 `EVALUATION_PLAN.md` 12장 참조.
