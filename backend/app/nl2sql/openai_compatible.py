"""OpenAI 兼容接口的最小 SQL 生成器。"""

from __future__ import annotations

import json
from typing import Callable
from urllib.request import Request, urlopen


class OpenAICompatibleSqlGenerator:
    """仅生成候选 SQL；真正的权限边界由 SQL guard 与只读账户共同承担。"""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        if not all((base_url.strip(), api_key.strip(), model.strip())):
            raise ValueError("llm_base_url, llm_api_key and llm_model are required")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    def generate(self, question: str, schema_context: str) -> str:
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": f"{schema_context}\n不要解释，只返回 SQL。",
                },
                {"role": "user", "content": question},
            ],
        }
        request = Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:  # nosec B310: URL comes from local config
            body = json.loads(response.read().decode("utf-8"))
        try:
            content = body["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError("llm_response_missing_sql") from exc
        return _strip_markdown(str(content))


def _strip_markdown(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return stripped.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
    return stripped
