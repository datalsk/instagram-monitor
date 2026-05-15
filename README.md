# instagram-monitor

인스타그램 계정에 새 게시물이 올라오면 메뉴 내용을 요약해 Slack DM으로 전송하는 자동화 봇입니다.  
AWS Lambda + EventBridge로 실행되며, 중복 발송 방지를 위해 DynamoDB에 마지막 게시물 마커를 저장합니다.

---

## 동작 흐름

```
EventBridge (5분 간격)
  → Lambda 실행
  → Instagram 최신 게시물 수집 (curl_cffi)
  → DynamoDB 마커와 비교
      ↳ 동일 → 종료 (중복 발송 없음)
      ↳ 새 게시물 → GPT-4o-mini로 내용 요약
          → 메뉴 게시물(🍱)이면 Slack DM 전송
          → DynamoDB 마커 업데이트
```

---

## 파일 구성

| 파일 | 설명 |
|------|------|
| `lambda_function.py` | Lambda 핸들러 (진입점) |
| `instagram_fetcher.py` | Instagram 내부 API로 최신 게시물 수집 |
| `summarizer.py` | OpenAI GPT-4o-mini로 메뉴 요약 |
| `storage.py` | DynamoDB 마커 읽기/쓰기 |
| `slack_notifier.py` | Slack Bot API로 DM 전송 |
| `deploy_lambda.py` | Lambda 코드 업데이트 + EventBridge 규칙 설정 |
| `run.py` | 로컬 테스트 실행용 |
| `requirements.txt` | 의존 패키지 목록 |

---

## 환경 변수

`.env` 파일(또는 Lambda 환경 변수)에 아래 값을 설정합니다.

```env
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-northeast-2

DYNAMODB_TABLE=instagram-monitor-state
INSTAGRAM_ACCOUNTS=account1,account2

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

SLACK_BOT_TOKEN=xoxb-...
SLACK_USER_IDS=U0XXXXXXX,U0YYYYYYY
```

---

## 배포

```bash
python deploy_lambda.py
```

- Lambda 패키지 빌드 (manylinux, Python 3.11)
- Lambda 함수 코드 및 환경 변수 업데이트
- EventBridge cron 규칙 활성화 (KST 11:00~11:30, 5분 간격)

---

## 로컬 테스트

```bash
pip install -r requirements.txt
python run.py
```

---

## Slack 수신자 추가/제거

1. 추가할 팀원의 Slack 프로필에서 **멤버 ID 복사** (`U`로 시작하는 값)
2. `.env`의 `SLACK_USER_IDS`에 콤마로 구분해 추가
3. `python deploy_lambda.py` 재배포

---

## 알림 조건

- **메뉴 게시물**(`🍱`로 시작하는 요약)일 때만 Slack 발송
- 메뉴가 아닌 일반 게시물은 발송하지 않음
- 오류 발생 시 Slack 발송 없이 Lambda 로그에만 기록
