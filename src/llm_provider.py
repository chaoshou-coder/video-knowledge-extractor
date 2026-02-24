"""
LLM provider - 统一异步客户端与配置加载
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping

import httpx

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - py3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass(frozen=True)
class ModelConfig:
    """单个模型配置"""

    api_base: str
    api_key: str
    model: str
    timeout: int = 120
    provider_only: list[str] = field(default_factory=list)
    provider_ignore: list[str] = field(default_factory=list)
    provider_order: list[str] = field(default_factory=list)
    provider_allow_fallbacks: bool | None = None
    provider_require_parameters: bool | None = None
    provider_data_collection: str | None = None
    provider_zdr: bool | None = None
    provider_sort: str | None = None
    response_format: Mapping[str, Any] | str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], section: str = "model") -> "ModelConfig":
        api_base = str(data.get("api_base", "")).strip()
        api_key = str(data.get("api_key", "")).strip()
        model = str(data.get("model", "")).strip()

        if not api_base:
            raise ValueError(f"{section}.api_base 不能为空")
        if not model:
            raise ValueError(f"{section}.model 不能为空")

        env_key = os.getenv("KL_MODEL_API_KEY", "").strip()
        if env_key:
            api_key = env_key
        if not api_key:
            raise ValueError(f"{section}.api_key 为空，请在配置中填写或设置 KL_MODEL_API_KEY")

        timeout_raw = data.get("timeout", 120)
        try:
            timeout = int(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{section}.timeout 必须为整数") from exc

        def _to_list(value: Any) -> list[str]:
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            return []

        def _to_bool(value: Any) -> bool | None:
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "y", "on"}:
                    return True
                if lowered in {"false", "0", "no", "n", "off"}:
                    return False
            return None

        provider_only = _to_list(data.get("provider_only"))
        provider_ignore = _to_list(data.get("provider_ignore"))
        provider_order = _to_list(data.get("provider_order"))
        provider_allow_fallbacks = _to_bool(data.get("provider_allow_fallbacks"))
        provider_require_parameters = _to_bool(data.get("provider_require_parameters"))
        provider_data_collection_raw = data.get("provider_data_collection")
        provider_data_collection = (
            str(provider_data_collection_raw).strip()
            if provider_data_collection_raw is not None
            else None
        )
        if provider_data_collection not in {None, "allow", "deny"}:
            raise ValueError(
                f"{section}.provider_data_collection 仅支持 allow / deny"
            )
        provider_zdr = _to_bool(data.get("provider_zdr"))
        provider_sort_raw = data.get("provider_sort")
        provider_sort = (
            str(provider_sort_raw).strip() if provider_sort_raw is not None else None
        )
        if provider_sort not in {None, "price", "throughput", "latency"}:
            raise ValueError(f"{section}.provider_sort 仅支持 price/throughput/latency")

        response_format = data.get("response_format")
        parsed_response_format: Mapping[str, Any] | str | None = None
        if response_format is not None:
            if isinstance(response_format, Mapping):
                parsed_response_format = {
                    str(key).strip(): value
                    for key, value in response_format.items()
                    if str(key).strip()
                }
            elif isinstance(response_format, str):
                normalized = response_format.strip()
                if normalized:
                    parsed_response_format = {"type": normalized}
            else:
                raise ValueError(f"{section}.response_format 类型不支持，请填写 table 或字符串")

        return cls(
            api_base=api_base.rstrip("/"),
            api_key=api_key,
            model=model,
            timeout=timeout,
            provider_only=provider_only,
            provider_ignore=provider_ignore,
            provider_order=provider_order,
            provider_allow_fallbacks=provider_allow_fallbacks,
            provider_require_parameters=provider_require_parameters,
            provider_data_collection=provider_data_collection,
            provider_zdr=provider_zdr,
            provider_sort=provider_sort,
            response_format=parsed_response_format,
        )


class LLMProvider:
    """统一异步 LLM 客户端（OpenAI Chat Completions 兼容）"""

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503}

    def __init__(
        self,
        config: ModelConfig,
        max_retries: int = 3,
        llm_semaphore: asyncio.Semaphore | None = None,
    ):
        self.config = config
        self.max_retries = max(0, int(max_retries))
        self._llm_semaphore = llm_semaphore
        timeout = httpx.Timeout(self.config.timeout)
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)

    async def close(self) -> None:
        await self._client.aclose()

    async def _post_chat(
        self, url: str, headers: Dict[str, str], payload: Dict[str, Any]
    ) -> httpx.Response:
        if self._llm_semaphore is None:
            return await self._client.post(url, headers=headers, json=payload)
        async with self._llm_semaphore:
            return await self._client.post(url, headers=headers, json=payload)

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        system_prompt: str | None = None,
        extra_payload: Dict[str, Any] | None = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.config.api_base:
            # OpenRouter 推荐附带这两个头，某些网关策略下可减少 4xx 风险。
            headers["HTTP-Referer"] = os.getenv("KL_APP_URL", "https://localhost")
            headers["X-Title"] = os.getenv("KL_APP_NAME", "video-knowledge-extractor")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        provider_payload: Dict[str, Any] = {}
        if self.config.provider_only:
            provider_payload["only"] = self.config.provider_only
        if self.config.provider_ignore:
            provider_payload["ignore"] = self.config.provider_ignore
        if self.config.provider_order:
            provider_payload["order"] = self.config.provider_order
        if self.config.provider_allow_fallbacks is not None:
            provider_payload["allow_fallbacks"] = self.config.provider_allow_fallbacks
        if self.config.provider_require_parameters is not None:
            provider_payload["require_parameters"] = self.config.provider_require_parameters
        if self.config.provider_data_collection is not None:
            provider_payload["data_collection"] = self.config.provider_data_collection
        if self.config.provider_zdr is not None:
            provider_payload["zdr"] = self.config.provider_zdr
        if self.config.provider_sort is not None:
            provider_payload["sort"] = self.config.provider_sort

        # 当 only 只给了一个 provider 且未配置 order 时，默认补齐 order
        # 可避免被价格策略干扰，确保优先命中该 provider。
        if (
            not self.config.provider_order
            and len(self.config.provider_only) == 1
            and "order" not in provider_payload
        ):
            provider_payload["order"] = list(self.config.provider_only)

        # 为了避免“only 指定 Azure 但实际回退到其他 provider”
        # 当用户配置 only 而未显式配置 allow_fallbacks 时，默认禁用 fallback。
        if self.config.provider_only and "allow_fallbacks" not in provider_payload:
            provider_payload["allow_fallbacks"] = False

        if provider_payload:
            payload["provider"] = provider_payload
        if extra_payload:
            payload.update(extra_payload)

        body: Dict[str, Any] | None = None
        last_err: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._post_chat(
                    f"{self.config.api_base}/chat/completions",
                    headers=headers,
                    payload=payload,
                )
                response.raise_for_status()
                body = response.json()
                break
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                resp_text = ""
                try:
                    resp_text = exc.response.text[:500]
                except Exception:
                    resp_text = "<无法读取响应体>"
                if (
                    status_code in self.RETRYABLE_STATUS_CODES
                    and attempt < self.max_retries
                ):
                    await asyncio.sleep(min(4.0, 0.8 * (attempt + 1)))
                    continue
                raise RuntimeError(
                    f"LLM HTTP {status_code} ({self.config.api_base}, model={self.config.model}): {resp_text}"
                ) from exc
            except (
                httpx.ReadError,
                httpx.RemoteProtocolError,
                httpx.ReadTimeout,
                httpx.ConnectError,
            ) as exc:
                last_err = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(min(4.0, 0.8 * (attempt + 1)))
            except Exception as exc:
                raise RuntimeError(
                    f"LLM 调用失败 ({self.config.api_base}, model={self.config.model}): {exc}"
                ) from exc

        if body is None:
            raise RuntimeError(
                f"LLM 连接不稳定，重试仍失败 ({self.config.api_base}, model={self.config.model}): {last_err}"
            )

        choices = body.get("choices") or []
        if not choices:
            raise ValueError("LLM 响应缺少 choices 字段")

        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            # 兼容多模态响应数组结构
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
            content = "".join(text_parts)

        text = str(content).strip()
        if not text:
            raise ValueError("LLM 返回内容为空")
        return text


class ProviderRegistry:
    """单模型配置容器（保留 Registry 名称以兼容调用方）"""

    def __init__(
        self,
        provider: LLMProvider,
        chunk_size: int = 60000,
        max_retries: int = 3,
        max_llm_concurrency: int = 8,
    ):
        self._provider = provider
        self.chunk_size = max(1000, int(chunk_size))
        self.max_retries = max(0, int(max_retries))
        self.max_llm_concurrency = max(1, int(max_llm_concurrency))

    def get(self) -> LLMProvider:
        return self._provider

    async def close(self) -> None:
        await self._provider.close()

    def summary(self) -> Dict[str, Any]:
        return {
            "api_base": self._provider.config.api_base,
            "model": self._provider.config.model,
            "provider_only": self._provider.config.provider_only,
            "provider_ignore": self._provider.config.provider_ignore,
            "provider_order": self._provider.config.provider_order,
            "provider_allow_fallbacks": self._provider.config.provider_allow_fallbacks,
            "provider_require_parameters": self._provider.config.provider_require_parameters,
            "provider_data_collection": self._provider.config.provider_data_collection,
            "provider_zdr": self._provider.config.provider_zdr,
            "provider_sort": self._provider.config.provider_sort,
            "response_format": self._provider.config.response_format,
            "chunk_size": self.chunk_size,
            "max_retries": self.max_retries,
            "max_llm_concurrency": self.max_llm_concurrency,
        }

    @classmethod
    def from_config(cls, config_path: Path) -> "ProviderRegistry":
        if not config_path.exists():
            raise FileNotFoundError(f"未找到配置文件: {config_path}")

        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        model_data = data.get("model")
        if not isinstance(model_data, dict):
            raise ValueError("配置文件缺少 [model] 段")

        config = ModelConfig.from_mapping(model_data, section="model")

        processing_data = data.get("processing", {})
        if not isinstance(processing_data, dict):
            processing_data = {}
        chunk_size_raw = processing_data.get("chunk_size", 60000)
        max_retries_raw = processing_data.get("max_retries", 3)
        max_llm_concurrency_raw = processing_data.get("max_llm_concurrency", 8)
        try:
            chunk_size = int(chunk_size_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("processing.chunk_size 必须为整数") from exc
        try:
            max_retries = int(max_retries_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("processing.max_retries 必须为整数") from exc
        try:
            max_llm_concurrency = int(max_llm_concurrency_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("processing.max_llm_concurrency 必须为整数") from exc
        if max_llm_concurrency < 1:
            raise ValueError("processing.max_llm_concurrency 必须 >= 1")
        if max_retries < 0:
            raise ValueError("processing.max_retries 必须 >= 0")

        llm_semaphore = asyncio.Semaphore(max_llm_concurrency)
        provider = LLMProvider(
            config=config,
            max_retries=max_retries,
            llm_semaphore=llm_semaphore,
        )
        return cls(
            provider=provider,
            chunk_size=chunk_size,
            max_retries=max_retries,
            max_llm_concurrency=max_llm_concurrency,
        )
