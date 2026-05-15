import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_APP_ID = "936619743392459"


class InstagramFetcher:
    def __init__(self, **kwargs):
        pass

    def get_latest_post(self, username: str) -> dict | None:
        from curl_cffi import requests as cffi_requests

        session = cffi_requests.Session(impersonate="chrome120")

        # 1단계: 프로필 페이지 방문 → csrftoken 쿠키 획득
        session.get(
            f"https://www.instagram.com/{username}/",
            headers={"Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=20,
        )

        # 2단계: 내부 API 호출
        resp = session.get(
            f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
            headers={
                "X-IG-App-ID": _APP_ID,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.instagram.com/{username}/",
                "Accept": "*/*",
            },
            timeout=20,
        )

        if resp.status_code != 200:
            logger.warning(f"@{username} — HTTP {resp.status_code}")
            raise RuntimeError(f"Instagram HTTP {resp.status_code}")

        data = resp.json()
        edges = (data.get("data", {})
                     .get("user", {})
                     .get("edge_owner_to_timeline_media", {})
                     .get("edges", []))

        if not edges:
            logger.info(f"@{username} — 게시물 없음")
            return None

        node = edges[0]["node"]
        shortcode = node["shortcode"]
        ts = node.get("taken_at_timestamp", 0)
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cap_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = cap_edges[0]["node"]["text"] if cap_edges else ""
        image_url = node.get("display_url") or node.get("thumbnail_src")
        post_url = f"https://www.instagram.com/p/{shortcode}/"
        marker = caption.split("\n")[0].strip()[:80] if caption else shortcode

        logger.info(f"@{username} — 최신 게시물: {marker[:60]}")
        return {
            "url": post_url,
            "date": date_str,
            "caption": caption,
            "likes": node.get("edge_liked_by", {}).get("count", 0),
            "comments": node.get("edge_media_to_comment", {}).get("count", 0),
            "marker": marker,
            "image_url": image_url,
        }
