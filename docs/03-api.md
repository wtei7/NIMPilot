# REST API

## 공통 사항

- Base URL: `http://localhost:8000`
- Content-Type: `application/json`
- 인증: `X-API-Key` 헤더 (향후 구현, 초기에는 없음)
- 에러 응답은 아래 통일된 형식을 따른다.

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "모델을 찾을 수 없습니다.",
    "details": {}
  }
}
```

### 에러 코드

| HTTP Status | Code                  | 설명                          |
|-------------|-----------------------|-------------------------------|
| 400         | BAD_REQUEST           | 잘못된 요청                      |
| 401         | UNAUTHORIZED          | 인증 실패                        |
| 404         | NOT_FOUND             | 리소스를 찾을 수 없음              |
| 409         | CONFLICT              | 상태 충돌 (예: 이미 실행 중)       |
| 500         | INTERNAL_ERROR        | 서버 내부 오류                    |
| 503         | SERVICE_UNAVAILABLE   | 외부 서비스(NVIDIA API 등) 오류  |

---

## Health & Status

### GET /health

서버 헬스 체크 (Docker health check용).

**Response** `200 OK`

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600
}
```

### GET /status

NIMPilot 전체 상태 조회.

**Response** `200 OK`

```json
{
  "litellm": {
    "status": "running",
    "pid": 12345,
    "port": 4000
  },
  "models_count": 20,
  "last_discover": "2025-07-10T12:00:00Z",
  "last_benchmark": "2025-07-10T12:30:00Z",
  "scheduler": {
    "enabled": true,
    "next_run": "2025-07-10T18:00:00Z"
  }
}
```

---

## Models

### GET /models

탐색된 모델 목록 조회.

**Query Parameters**

| Parameter  | Type   | Required | Description        |
|------------|--------|----------|--------------------|
| `category` | string | No       | 필터: coding, chat, reasoning 등 |
| `search`   | string | No       | 모델명 검색           |

**Response** `200 OK`

```json
{
  "models": [
    {
      "id": "nvidia/llama-3.1-nemotron-70b-instruct",
      "name": "Llama-3.1-Nemotron-70B-Instruct",
      "alias": "nemotron-70b",
      "context_length": 131072,
      "capabilities": ["chat", "tool_calling", "json_mode"],
      "status": "available"
    }
  ],
  "total": 20
}
```

### GET /models/{model_id}

단일 모델 상세 조회.

**Response** `200 OK`

```json
{
  "id": "nvidia/llama-3.1-nemotron-70b-instruct",
  "name": "Llama-3.1-Nemotron-70B-Instruct",
  "alias": "nemotron-70b",
  "context_length": 131072,
  "input_token_limit": 131072,
  "output_token_limit": 4096,
  "capabilities": ["chat", "tool_calling", "json_mode"],
  "description": "...",
  "status": "available"
}
```

`404 NOT_FOUND` — 모델이 존재하지 않음.

---

## Benchmarks

### GET /benchmarks

벤치마크 결과 조회.

**Query Parameters**

| Parameter   | Type   | Required | Description                    |
|-------------|--------|----------|--------------------------------|
| `model_id`  | string | No       | 특정 모델 필터                   |
| `metric`    | string | No       | 특정 메트릭 필터 (ttft, tps 등)   |

**Response** `200 OK`

```json
{
  "benchmarks": [
    {
      "model_id": "nvidia/llama-3.1-nemotron-70b-instruct",
      "timestamp": "2025-07-10T12:30:00Z",
      "metrics": {
        "ttft_ms": 120.5,
        "tps": 85.3,
        "latency_ms": 450.2,
        "streaming_tps": 82.1,
        "tool_calling_success": true,
        "json_mode_success": true
      }
    }
  ]
}
```

### POST /benchmark

벤치마크 실행.

**Request Body**

```json
{
  "model_ids": ["nvidia/llama-3.1-nemotron-70b-instruct"],
  "metrics": ["ttft", "tps", "latency"]
}
```

| Field       | Type     | Required | Description                          |
|-------------|----------|----------|--------------------------------------|
| `model_ids` | string[] | No       | 벤치마크 대상 모델 목록 (생략 시 전체)  |
| `metrics`   | string[] | No       | 측정할 메트릭 (생략 시 전체)           |

**Response** `202 Accepted`

```json
{
  "task_id": "bench-20250710-001",
  "status": "running",
  "model_count": 20
}
```

`409 CONFLICT` — 이미 벤치마크가 실행 중.

---

## Recommendations

### GET /recommendations

모델 추천 목록 조회.

**Query Parameters**

| Parameter  | Type   | Required | Description                     |
|------------|--------|----------|---------------------------------|
| `profile`  | string | No       | 프로필 기반 추천 (coding, chat 등) |
| `limit`    | int    | No       | 반환 개수 (기본 5)                 |

**Response** `200 OK`

```json
{
  "recommendations": [
    {
      "rank": 1,
      "model_id": "nvidia/llama-3.1-nemotron-70b-instruct",
      "score": 95.5,
      "reason": "코딩 작업에서 최고 성능"
    }
  ]
}
```

---

## Discover

### POST /discover

NVIDIA 모델 재탐색 실행.

**Response** `202 Accepted`

```json
{
  "task_id": "discover-20250710-001",
  "status": "running"
}
```

`409 CONFLICT` — 이미 탐색 중.

---

## Config

### POST /generate-config

LiteLLM Config YAML 재생성.

**Response** `200 OK`

```json
{
  "status": "generated",
  "file": "config/generated.yaml",
  "model_count": 20
}
```

### POST /reload

LiteLLM 설정 Reload.

**Response** `200 OK`

```json
{
  "status": "reloaded"
}
```

---

## Router

### GET /router/config

현재 Router 설정 조회.

**Response** `200 OK`

```json
{
  "mode": "auto",
  "fallback_model": "nvidia/llama-3.1-nemotron-70b-instruct",
  "rules": []
}
```

### POST /router/reload

Router 설정 Reload.

**Request Body**

```json
{
  "mode": "auto"
}
```

**Response** `200 OK`

```json
{
  "status": "reloaded",
  "mode": "auto"
}
```

---

## Profiles

### GET /profiles

프로필 목록 조회.

**Response** `200 OK`

```json
{
  "profiles": [
    {
      "name": "coding",
      "description": "코딩에 최적화된 모델 선택",
      "preferred_metrics": ["tool_calling", "json_mode"],
      "model_ids": ["nvidia/llama-3.1-nemotron-70b-instruct"]
    }
  ]
}
```

### POST /profiles

프로필 생성 또는 수정.

**Request Body**

```json
{
  "name": "my-coding-profile",
  "description": "나의 커스텀 코딩 프로필",
  "preferred_metrics": ["tool_calling", "json_mode", "tps"],
  "model_ids": ["nvidia/llama-3.1-nemotron-70b-instruct"]
}
```

**Response** `201 Created`

```json
{
  "status": "created",
  "name": "my-coding-profile"
}
```

`400 BAD_REQUEST` — 잘못된 프로필 이름 또는 중복.