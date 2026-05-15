import json
import os
import logging
from datetime import datetime, timezone, timedelta
from instagram_fetcher import InstagramFetcher
from summarizer import PostSummarizer
from storage import DynamoDBStorage
from slack_notifier import SlackNotifier

logger = logging.getLogger()
logger.setLevel(logging.INFO)

KST = timezone(timedelta(hours=9))


def lambda_handler(event, context):
    accounts_env = os.environ.get("INSTAGRAM_ACCOUNTS", "family_koreanfood")
    target_accounts = [a.strip() for a in accounts_env.split(",") if a.strip()]

    fetcher = InstagramFetcher()
    summarizer = PostSummarizer()
    storage = DynamoDBStorage()
    notifier = SlackNotifier()

    for account in target_accounts:
        try:
            _process_account(account, fetcher, summarizer, storage, notifier)
        except Exception as e:
            logger.error(f"Unhandled error for @{account}: {e}", exc_info=True)

    return {"statusCode": 200}


def _process_account(account, fetcher, summarizer, storage, notifier):
    # 1. 이전 마커 로드
    state = storage.get_state(account)
    last_marker = state.get("last_seen_post_marker", "") if state else ""
    logger.info(f"@{account} — last marker: {last_marker!r}")

    # 2. 최신 게시물 가져오기
    latest_post = fetcher.get_latest_post(account)
    if not latest_post:
        logger.info(f"@{account} — no posts found")
        return

    current_marker = latest_post["marker"]
    logger.info(f"@{account} — current marker: {current_marker!r}")

    # 3. 동일 게시물이면 체크 시각만 갱신
    if current_marker == last_marker:
        logger.info(f"@{account} — no new post, skipping")
        storage.update_checked_at(account)
        return

    # 4. 새 게시물 → 요약
    logger.info(f"@{account} — new post detected!")
    summary = summarizer.summarize(account, latest_post)

    # 5. 메뉴 게시물일 때만 Slack DM 전송 (이미지 첨부)
    if summary.startswith("🍱"):
        notifier.send_new_post(account, summary, latest_post.get("image_url"))
    else:
        logger.info(f"@{account} — 메뉴 게시물 아님, Slack 전송 생략")

    # 6. 전송 성공 시만 마커 업데이트 (실패 시 예외가 터져서 여기 도달 안 함)
    storage.update_state(account, current_marker)
    logger.info(f"@{account} — state updated to: {current_marker!r}")
