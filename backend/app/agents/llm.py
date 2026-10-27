"""LLM 客户端：统一封装模型分工、并发控制、重试与 Token 计费统计。

设计取舍：
- 不用通用框架封装，因为需要严格控制成本（廉价模型做抽取与命名，
  主力模型只用于空白批判与综述生成）并逐次记录 token 与耗时，
  这些数据直接进入评测报告与前端成本面板。
- 未配置 API key 时不做任何网络调用，直接返回 None，由调用方走确定性降级路径。
  这保证系统在无 key 环境下依然完整可用（离线场景下的降级保障）。
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class LLMUsage:
    """调用统计：用于成本核算与评测报告。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_seconds: float = 0.0
    failures: int = 0
    per_model: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "failures": self.failures,
            "per_model": self.per_model,
        }


class LLMClient:
    """主力 / 廉价双模型客户端。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any = None
        self._semaphore = asyncio.Semaphore(max(1, self._settings.llm_max_concurrency))
        self.usage = LLMUsage()

    @property
    def available(self) -> bool:
        return self._settings.has_llm

    @property
    def cheap_model(self) -> str:
        return self._settings.llm_model_cheap

    @property
    def main_model(self) -> str:
        return self._settings.llm_model_main

    def _ensure_client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._settings.deepseek_api_key,
                base_url=self._settings.deepseek_base_url,
                timeout=self._settings.llm_timeout,
            )
        return self._client

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> str | None:
        """单次补全，失败返回 None（调用方负责降级）。"""
        if not self.available:
            return None

        target_model = model or self.cheap_model
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens

        started = time.monotonic()
        async with self._semaphore:
            for attempt in range(max(1, self._settings.llm_max_retries)):
                try:
                    response = await self._ensure_client().chat.completions.create(**payload)
                    self._record(response, target_model, time.monotonic() - started)
                    return response.choices[0].message.content
                except Exception as exc:  # noqa: BLE001
                    self.usage.failures += 1
                    if attempt == max(1, self._settings.llm_max_retries) - 1:
                        print(f"[llm] 调用失败（{target_model}）: {type(exc).__name__}: {exc}")
                        return None
                    await asyncio.sleep(1.5 * (attempt + 1))
        return None

    async def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> dict | None:
        """要求结构化 JSON 输出，并容错处理模型偶发的代码块包裹。"""
        raw = await self.complete(
            prompt, system=system, model=model, temperature=temperature, json_mode=True
        )
        if not raw:
            return None
        return parse_json_response(raw)

    def _record(self, response: Any, model: str, elapsed: float) -> None:
        self.usage.calls += 1
        self.usage.elapsed_seconds += elapsed
        self.usage.per_model[model] = self.usage.per_model.get(model, 0) + 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.usage.completion_tokens += getattr(usage, "completion_tokens", 0) or 0


def parse_json_response(raw: str) -> dict | None:
    """从模型输出中稳健地提取 JSON 对象。

    模型常把 JSON 包在代码块里或前后附带说明文字，这里逐级容错。
    """
    text = (raw or "").strip()
    if not text:
        return None

    block = _JSON_BLOCK_RE.search(text)
    if block:
        text = block.group(1).strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None
