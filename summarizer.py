import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM = """당신은 인스타그램 게시물 캡션을 읽고 한국어로 요약하는 어시스턴트입니다.
해시태그는 요약에서 완전히 제외하세요."""

_PROMPT = """다음 인스타그램 캡션을 분석하고 아래 지시에 따라 요약하세요.

---캡션 시작---
{caption}
---캡션 끝---

게시 날짜: {date}
게시물 URL: {url}

[메뉴 게시물인 경우] 다음 형식을 정확히 따르세요:
🍱 *가족한식뷔페 새 메뉴 알림* ({date_short})

*메인*
• (메인 요리 목록)

*국*
• (국 종류)

*반찬*
• (반찬 목록)

*쌈/김치*
• (쌈, 김치)

🔗 {url}

[메뉴 게시물이 아닌 경우] 3~5줄로 자연스럽게 요약한 뒤 마지막에 🔗 {url} 를 추가하세요.

규칙:
- 해시태그(#으로 시작하는 단어) 완전 제거
- 날짜는 캡션 또는 게시 날짜에서 추출
- 링크는 항상 마지막에 포함"""


class PostSummarizer:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def summarize(self, account: str, post: dict) -> str:
        date_short = post["date"][:10]
        prompt = _PROMPT.format(
            caption=post["caption"],
            date=post["date"],
            date_short=date_short,
            url=post["url"],
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=512,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content.strip()
