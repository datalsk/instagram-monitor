import boto3
import os
import logging
from datetime import datetime, timezone, timedelta
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class DynamoDBStorage:
    def __init__(self):
        # Lambda: IAM 역할로 자동 인증 (boto3 기본 체인 사용)
        # 로컬: AWS_ACCESS_KEY_ID 등 환경변수를 boto3가 자동으로 읽음
        self.table = boto3.resource(
            "dynamodb",
            region_name=os.environ.get("AWS_REGION", "ap-northeast-2"),
        ).Table(os.environ.get("DYNAMODB_TABLE", "instagram-monitor-state"))

    def get_state(self, account: str) -> dict | None:
        resp = self.table.get_item(Key={"pk": f"state#{account}"})
        return resp.get("Item")

    def update_state(self, account: str, marker: str) -> None:
        self.table.put_item(Item={
            "pk": f"state#{account}",
            "account": account,
            "last_seen_post_marker": marker,
            "last_checked_at": _now_kst(),
            "ttl": _ttl_90days(),
        })
        logger.info(f"State saved for @{account}: {marker!r}")

    def update_checked_at(self, account: str) -> None:
        """새 게시물 없을 때 체크 시각만 갱신."""
        self.table.update_item(
            Key={"pk": f"state#{account}"},
            UpdateExpression="SET last_checked_at = :t",
            ExpressionAttributeValues={":t": _now_kst()},
        )


def _now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _ttl_90days() -> int:
    return int(datetime.now().timestamp()) + 90 * 24 * 3600
