"""Public job discovery uses a fixed API origin, never arbitrary URLs."""

import json
import re
from html import unescape

import httpx

from .models import Job


def greenhouse(board: str, client: httpx.Client) -> list[Job]:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", board):
        raise ValueError("Invalid Greenhouse board identifier")
    # Enforce the decoded byte limit during intake, before buffering/parsing the board.
    with client.stream(
        "GET",
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
        params={"content": "true"},
        headers={"Accept-Encoding": "identity"},
        timeout=20,
        follow_redirects=False,
    ) as response:
        response.raise_for_status()
        if response.headers.get("content-encoding", "identity").casefold() != "identity":
            raise ValueError("Unsupported job board content encoding")
        content = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            if len(content) + len(chunk) > 5_000_000:
                raise ValueError("Job board response exceeds the local size limit")
            content.extend(chunk)
    result: list[Job] = []
    for item in json.loads(content)["jobs"]:
        # Section headings and bullet boundaries are needed by requirement interpretation.
        html = re.sub(
            r"</?(?:p|div|section|li|ul|ol|h[1-6]|br)\b[^>]*>",
            "\n",
            item.get("content", ""),
            flags=re.I,
        )
        text = unescape(re.sub(r"<[^>]+>", " ", html))
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
