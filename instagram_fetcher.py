import logging
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


class InstagramFetcher:
    def __init__(self, **kwargs):
        pass

    def get_latest_post(self, username: str) -> dict | None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="ko-KR",
            )

            captured = {}

            def on_response(response):
                if "web_profile_info" in response.url and response.status == 200:
                    try:
                        data = response.json()
                        edges = (data.get("data", {})
                                     .get("user", {})
                                     .get("edge_owner_to_timeline_media", {})
                                     .get("edges", []))
                        if edges:
                            captured["edges"] = edges
                    except Exception:
                        pass

            page = context.new_page()
            page.on("response", on_response)
            page.goto(f"https://www.instagram.com/{username}/",
                      wait_until="networkidle", timeout=30000)
            browser.close()

        edges = captured.get("edges")
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
