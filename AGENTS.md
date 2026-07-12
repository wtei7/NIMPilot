# AGENTS.md

## 개발 원칙

- 먼저 docs를 모두 읽고 프로젝트를 이해한다.
- 현재 Task만 구현한다.
- Task 범위를 벗어나는 기능은 구현하지 않는다.
- 기존 구조를 임의로 변경하지 않는다.
- 큰 리팩터링은 요청받기 전까지 하지 않는다.
- 새로운 라이브러리를 추가할 경우 이유를 설명한다.
- 모든 코드에는 타입 힌트를 사용한다.
- PEP8을 준수한다.

## 작업 완료 후 반드시 보고

- 변경된 파일 목록
- 변경 이유
- 테스트 결과
- 다음 Task 제안
- 발견한 문제점 및 개선 아이디어

## Workflow

For every task:

1. Read the relevant docs and the current task.
2. Explain the implementation plan before writing code.
3. Implement only the current task.
4. Run or describe validation/tests.
5. Report:
   - Files changed
   - Summary of changes
   - Remaining TODOs
   - Suggested next task

Never implement features outside the current task unless explicitly requested.