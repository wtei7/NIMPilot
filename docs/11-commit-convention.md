# 커밋 규칙 (Commit Convention)

## 커밋 메시지 형식

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

| Type | 설명 |
|------|------|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서 변경 |
| `style` | 코드 포맷팅, 세미콜론 누락 등 (기능 변경 없음) |
| `refactor` | 코드 리팩토링 (기능 변경 없음) |
| `test` | 테스트 추가 또는 수정 |
| `chore` | 빌드, 설정, 의존성 등 기타 작업 |
| `ci` | CI 설정 변경 |

### Scope

Task 번호 또는 모듈명을 사용:

- `task-000` ~ `task-012`: 각 Task에 해당하는 변경
- `discover`, `generator`, `benchmark`, `router`, `dashboard`, `api`, `scheduler`: 모듈명
- `config`, `storage`, `utils`: 기반 모듈

### Subject

- 50자 이내
- 마침표 없음
- 명령형 (예: "Add model discovery engine" → "모델 탐색 엔진 추가")
- 한글 또는 영문 가능

### Body

- 72자마다 줄바꿈
- "무엇을", "왜" 변경했는지 설명 ( "어떻게"는 코드로 설명)

### Footer

- Breaking Changes: `BREAKING CHANGE:` 접두사
- 관련 이슈: `Closes #123`, `Refs #456`

## 커밋 예시

```
feat(task-000): 기반 모듈 구현 (config_manager, storage, utils)

- Pydantic 기반 AppConfig 모델 정의
- JsonStorageBackend 구현 (원자적 쓰기, 스레드 안전)
- NIMPilotError 예외 계층 구조
- setup_logging, retry 데코레이터 등 유틸리티 함수

Task 000 (Foundation) 완료.
```

```
feat(task-001): 프로젝트 초기화 및 Docker 환경 구성

- FastAPI 앱 생성 및 /health 엔드포인트
- Dockerfile 및 docker-compose.yml 작성
- Python 가상환경(.venv) 설정 및 스크립트 연동
- requirements.txt, .env.example, .gitignore, README.md

Task 001 (Project Init) 완료.
```

```
feat(task-002): NVIDIA NIM 모델 탐색 엔진 구현

- DiscoverEngine 클래스 (fetch → parse → save 파이프라인)
- NVIDIA NIM API /models 호출 (httpx, retry, 에러 처리)
- 모델 alias 자동 생성
- capabilities 추정 로직
- 17개 테스트 (alias, parse, save, fetch, 통합)

Task 002 (Discover Models) 완료.
```

## 브랜치 규칙

- `main`: 배포 가능한 안정 브랜치
- `feature/<task-number>-<name>`: Task별 기능 개발 브랜치
- `fix/<issue>-<name>`: 버그 수정 브랜치

## 커밋 원칙

1. **하나의 커밋 = 하나의 논리적 변경**
   - Task 단위로 커밋을 분리
   - 서로 다른 기능은 별도 커밋으로

2. **커밋 전 테스트 통과 필수**
   - `python -m pytest tests/ -v` 통과 확인

3. **Push는 명시적 요청 시에만**
   - 커밋은 로컬에만 유지
   - 사용자 승인 후 `git push` 실행

4. **.venv, __pycache__, .env는 커밋하지 않음**
   - `.gitignore`에 등록됨