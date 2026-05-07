import os
import json
import urllib.request
import urllib.error
import logging

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api/chat.postMessage"


class SlackNotifier:
    def __init__(self):
        token = os.environ["SLACK_BOT_TOKEN"]
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        raw = os.environ.get("SLACK_USER_IDS", "")
        self.user_ids = [uid.strip() for uid in raw.split(",") if uid.strip()]
        if not self.user_ids:
            raise ValueError("SLACK_USER_IDS 환경변수가 없습니다")

    def send_new_post(self, account: str, summary: str, image_url: str | None = None) -> None:
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        ]
        if image_url:
            blocks.append({
                "type": "image",
                "image_url": image_url,
                "alt_text": "메뉴 대표 이미지",
            })
        for uid in self.user_ids:
            self._post({"channel": uid, "text": summary, "blocks": blocks})
        logger.info(f"Slack 전송 완료 (@{account}) → {self.user_ids}")

    def send_error(self, account: str, error: str) -> None:
        text = f":warning: `@{account}` 오류: {error}"
        for uid in self.user_ids:
            self._post({"channel": uid, "text": text})

    def _post(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(SLACK_API, data=data, headers=self.headers, method="POST")
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = json.loads(resp.read())
                    if not body.get("ok"):
                        raise RuntimeError(f"Slack API 오류: {body.get('error')}")
                return
            except urllib.error.URLError as e:
                if attempt == 0:
                    logger.warning(f"Slack 재시도: {e}")
                    continue
                raise
