# CLAUDE.md

이 파일은 Claude Code(claude.ai/code)가 이 저장소에서 작업할 때 참고하는 가이드입니다.

## 프로젝트 개요

FastAPI + Celery + Redis 기반의 비동기 푸시 알림 시스템으로, 멀티 워커 환경을 목표로 한다. 

핵심 목표:
- **멱등성**: Redis 기반 중복 제거로 워커 간 푸시 중복 전송 방지
- **안정성**: Retry 로직 + DLQ(Dead Letter Queue)로 워커 crash 시 메시지 유실 방지

Node.js + SQS 기반 시스템의 단일 워커 한계를 해결하기 위한 재구현 프로젝트다.

## 기술 스택
* 언어: Python 3.12
* 프레임워크: FastAPI
* 비동기 처리: Celery
* 메시지 브로커: Redis
* 데이터베이스: Supabase (PostgreSQL)
* Redis 실행 환경: Docker
* 패키지 관리: uv
* 린트/포맷: ruff
* 테스트: pytest

## 아키텍처 
- 기능별 디렉토리 구조 분리 (api / core / schemas / services / tasks)

## 주요 명령어
```bash
uv run python main.py          # 앱 실행
uv run fastapi dev             # FastAPI 개발 서버 시작
uv run ruff check .            # 린트
uv run ruff format .           # 포맷
uv run ruff check --fix .      # 린트 자동 수정
```
## 코드 규칙
- 타입 힌트 필수화: 모든 함수의 매개변수와 반환값은 명확한 타입 힌트 적용
- 요청/응답 스키마 분리: 데이터 입출력 검증은 Pydatic 모델 사용. 스키마 목적에 맞게 분리해서 정의

## 테스트 규칙
- pytest 사용
- services, celery tasks 비즈니스 로직은 unit test 필수
- FastAPI dependency는 override하여 테스트
- 외부 의존성(DB, Redis)은 mock 처리
- e2e는 핵심 엔드포인트만 TestClient 기반으로 작성
- 테스트 결과는 `pytest --html=report.html`로 리포트 생성

## 에러 처리
- 모든 에러는 공통 에러 객체로 반환
- HTTP 상태 코드 명확히 사용

## 중요 사항
- 아키텍처, DB 등의 상세 내용은 `docs/` 폴더를 참조한다. 
- 비밀번호, 주요 키 등은 하드코딩 하지 않고, 환경변수 파일로 관리한다. `.env`은 git에 커밋하지 않는다.
- API는 Celery task enqueue만 수행한다.
- 외부 서비스 호출은 worker에서만 수행한다.
- 한 작업(기능/수정) 단위마다 커밋한다.
