# Phase 5 — Task lifecycle API (2026-10-23)

구현 계약은 `app/task_api.py`와 `/openapi.json`, 클라이언트 타입은
`frontend/src/types.ts`다. 기존 `POST /api/plan`의 입력·응답·status는 유지한다.
새 API는 기존 독립 요청 검토 → 계획 생성/의미 검증 → 시작 직전 재검증 →
Service/ActionPolicy/Engine을 호출한다. 클라이언트가 계획·상태·검토 결과나
`VerificationContext`를 업로드해서 승인받는 stateless 방식은 사용하지 않는다.

## 생성·조회·이벤트

| 메서드·경로 | 입력 | 정상 응답 |
|---|---|---|
| `POST /api/v1/tasks` | `goal`, `transcript`, 기존 `user_profile` | `decision`, `reason_code`, `session` 또는 `null` |
| `GET /api/v1/tasks/{task_id}` | 서버 발급 task ID | 최신 상태를 재검증한 `TaskSessionResponse` |
| `POST /api/v1/tasks/{task_id}/events` | `event_id`, `expected_version`, `event` | 이벤트 처리·재검증 후 `TaskSessionResponse` |

생성 예시(합성 프로필·현재 지원 영어 문법):

```json
{
  "goal": "locate_mug_only",
  "transcript": "Only help me locate the mug.",
  "user_profile": {"user_id": "synthetic", "preferred_guidance": ["voice"]}
}
```

세션 응답에는 `task_id`, `version`, `plan`, `state`, 실제 proposal의 `mode`,
이번 처리의 `accepted`, `reason_code`, `cue`(최대 1개 또는 null), `events`가 있다.
`plan`은 미실행 후속 물리 단계를 포함하는 **제안 데이터**다. 렌더러는 승인된
현재 `cue`만 안내로 사용해야 한다. plan 텍스트/action 자체가 행동 허가는 아니다.
`state`의 완료 이력/Evidence와 이번 호출의 audit events를 구분한다.
events는 전체 누적 저널이 아니며, 응답 수신은 실제 UI 노출·음성 재생의 증거가 아니다.

pause 예시(`event_id`는 클라이언트가 재시도 시 유지):

```json
{
  "event_id": "synthetic-pause-1",
  "expected_version": 1,
  "event": {"type": "pause"}
}
```

지원 event는 `pause`, `resume`, `stop`, `refusal`, `more_help`, `help_requested`,
`manual_advance`, `cue_issued`, `target_bound`, `evidence_received`다. payload의
구조·필수 필드는 OpenAPI를 따른다. `cue_issued`는 현재 단계의 **안내 요청**으로
처리하고 gate 뒤 서버가 발행을 기록한다. 클라이언트의 노출/성공 주장을 신뢰하지
않는다. `manual_advance`는 확인 필요 상태로 전환하며 완료나 단계 이동을 만들지 않는다.

## 세션·버전·오류

- 서버 메모리에 plan·review·state·선호와 이미 처리한 event ID를 보관한다.
  생성 버전은 1이다. 세션별 lock 안에서 버전 검사와 상태 갱신을 함께 처리한다.
- 구조가 유효하고 버전이 일치한 이벤트 시도는 정책 거부·확인 보류를 포함해
  버전을 1 증가시키고 ID를 소비한다. `accepted=false`여도 새 상태를 사용한다.
  이전 단계의 Evidence는 수용됐지만 다음 물리 단계가 막힌 응답일 수도 있다.
- 중복 event ID는 `409 duplicate_event_id`, 버전 불일치는
  `409 state_version_conflict`다. 큐나 과거 성공 응답을 재발행하지 않는다.
  새 event ID와 최신 조회 버전으로 의도한 작업을 다시 판단한다.
- GET은 cue를 발행하거나 도움 수준을 올리지 않는다. active 상태에서 최신 context가 기존 binding을
  stale로 만들면 hold를 저장하고 버전도 증가한다. 상태가 같으면 버전은 유지한다.
  pause를 해제하는 resume도 최신 맥락을 재검증한다. confirmation/assistance hold는
  polling/resume으로 해제하지 않는다. 별도 승인·hold 해제 흐름은 아직 없다.
- 잘못된 구조는 `422`, 없는 세션은 `404 task_not_found`, terminal 상태의 새 이벤트는
  `409 terminal_state`다. 이 오류들은 상태·버전·event ID를 바꾸지 않는다.
  유효 구조의 잘못된 전이·stale/미관찰/무근거 Evidence는 `200`의
  `accepted=false`와 안전 상태·reason으로 반환한다. 행동 cue는 없다.
- 기본 한도는 세션 100개(terminal 포함), 세션당 순서 검사를 통과한 이벤트
  1,000개다. 생성 중인 요청도 세션 한도에 포함하며 초과 시 모델 호출 전에
  `503 session_capacity_reached`다. 이벤트 한도는 `409 event_capacity_reached`이며
  stop/refusal은 끝내기 위해 추가 1회 허용한다. 이후 terminal 규칙이 적용된다.
  자동 퇴거·삭제 API는 없다. 생성 POST의 재시도는 별도 새 과제가 된다.

## 관찰·Evidence·모델 경계

기본 `TaskSessions.context()`는 observation revision=`unobserved`, 객체 없음,
profile에 명시된 기존 세 능력만 전달하며 receipt/principal/물리 fact는 없다.
locate 인지 지원을 시작할 수 있어도 물리 수행·완료를 승인하지 않는다.
API는 클라이언트의 관찰·receipt·principal·feasibility·의미 검토 업로드 필드를
받지 않는다. `target_bound`/`evidence_received`는 후보일 뿐이며 기존 검증으로
현재 관찰·revision·task/plan scope·정확한 receipt·허용 source를 대조한다.
후보의 source=`caregiver_report`만으로 보호자 인증이나 완료가 성립하지 않는다.
실제 source 인증·관찰·UI 연결은 **Phase 6 미구현**이다. 테스트 어댑터의 합성
receipt는 운영 기본값에 들어가지 않는다. bbox 필드는 새 cue에 없고,
visual cue의 object ID/revision은 일치하는 관찰의 좌표를 조회할 때만 사용한다.

생성 provider는 `PLANNER_MODE=live`와 기존 서버 `.env`의 유효 Nebius 설정이
필요하다. demo 모드이면 `502 live_mode_required`, provider/schema 오류이면
기존 sanitized `PlanningError.reason_code`로 502이며 세션을 만들지 않는다.
demo·fixture·Template fallback은 없다. 독립 요청 검토의 보류/거부는 provider
생성·호출 없이 confirm/stop와 session=null이다. 명시 모델 보류는
`model_abstained`, legacy `{}`는 `model_no_plan`으로 session=null이며,
선언 사유가 사실이라고 승인하지 않는다.

이번 Phase 검증은 **MOCK_PROVIDER + 합성 backend observation/receipt** 및 기존
DEMO_RULES 회귀다. 새 LIVE_NEBIUS 호출, 실제 DEMO_SCENE 수집·카메라·신체 수행·
브라우저/TTS 검증은 하지 않았다. 기존 E4 결과를 새 API의 실환경 성공으로 세지 않는다.

## 배포 한계

단일 프로세스·단일 worker의 로컬 합성 데모만 지원한다. 재시작하면 세션과
중복 ID가 모두 사라져 기존 task ID는 404가 된다. worker 간 메모리를 공유하지
않으므로 여러 worker/instance에서 일관성·조회·중복 차단을 보장하지 않는다.
DB·분산 동시성·영속 저널은 Phase 7의 별도 범위다.

task ID는 무작위 128-bit UUID possession handle이다. 계정 인증·사용자별 권한
검사는 구현하지 않았다. task ID를 아는 호출자가 조회·제어할 수 있으므로 로컬
합성 데모 범위를 유지한다. 프로필의 user_id는 인증 주체가 아니다.
raw transcript/합성 profile은 세션 메모리에만 보관하고 새 로그를 남기지 않는다.

검증 명령: backend에서 `uv run pytest`, `uv run ruff check .`, frontend에서
`npm run typecheck`, `npm run build`. HTTP 테스트는 `tests/test_task_api.py`다.
