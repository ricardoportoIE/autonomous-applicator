"""Public job discovery uses a fixed API origin, never arbitrary URLs."""

import re
from html import unescape

import httpx

from .models import Job


def greenhouse(board: str, client: httpx.Client) -> list[Job]:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", board):
        raise ValueError("Invalid Greenhouse board identifier")
    response = client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
        params={"content": "true"},
        timeout=20,
        follow_redirects=False,
    )
    response.raise_for_status()
    if len(response.content) > 5_000_000:
        raise ValueError("Job board response exceeds the local size limit")
    result: list[Job] = []
    for item in response.json()["jobs"]:
        text = unescape(re.sub(r"<[^>]+>", " ", item.get("content", "")))
        if text.strip():
            result.append(
                Job(
                    source="greenhouse",
                    source_id=f"{board}:{item['id']}",
                    title=item["title"],
                    company=board,
                    location=item["location"]["name"],
                    url=item["absolute_url"],
                    description=text,
                )
            )
    return result
