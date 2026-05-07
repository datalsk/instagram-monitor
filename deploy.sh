#!/bin/bash
set -e

# .env 로드
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "[오류] .env 파일이 없습니다. .env.example을 복사해서 만드세요."
  exit 1
fi

echo "=== SAM 빌드 중... ==="
sam build

echo "=== SAM 배포 중... ==="
sam deploy \
  --stack-name instagram-monitor \
  --region "${AWS_REGION:-ap-northeast-2}" \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --parameter-overrides \
    InstagramAccounts="${INSTAGRAM_ACCOUNTS}" \
    AnthropicApiKey="${ANTHROPIC_API_KEY}" \
    SlackWebhookUrl="${SLACK_WEBHOOK_URL}" \
    SlackWebhookUrl2="${SLACK_WEBHOOK_URL_2:-}" \
    PollIntervalMinutes="10"

echo ""
echo "=== 배포 완료 ==="
echo "Lambda가 매일 KST 10:00~11:30 사이 10분마다 @${INSTAGRAM_ACCOUNTS} 계정을 체크합니다."
echo "새 게시물 감지 시 Slack 웹훅으로 자동 전송됩니다."
