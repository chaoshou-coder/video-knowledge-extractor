"""LLM Client - 支持本地 Ollama 和 API"""

import requests
import json
from typing import Optional


class LLMClient:
    """LLM 客户端基类"""

    def extract_knowledge(self, text: str) -> dict:
        """提取知识，返回结构化数据"""
        raise NotImplementedError


class OllamaClient(LLMClient):
    """本地 Ollama 客户端"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama2"):
        self.base_url = base_url
        self.model = model

    def extract_knowledge(self, text: str) -> dict:
        """调用本地 Ollama 提取知识"""
        prompt = f"""从以下讲座内容中提取结构化知识：

{text[:3000]}

请提取：
1. 核心主题（一句话概括）
2. 关键概念（3-5个）
3. 重要知识点（列表形式）
4. 总结（100字以内）

以 JSON 格式返回：
{{
  "topic": "...",
  "concepts": ["...", "..."],
  "key_points": ["...", "..."],
  "summary": "..."
}}"""

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()

            # 解析返回的 JSON
            content = result.get("response", "")
            # 尝试提取 JSON 部分
            try:
                # 查找 JSON 块
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(content[start:end])
                    return data
            except Exception:
                pass

            # 如果 JSON 解析失败，返回原始内容
            return {
                "topic": "提取失败",
                "concepts": [],
                "key_points": [content[:500]],
                "summary": "",
            }

        except Exception as e:
            return {
                "topic": f"错误: {str(e)}",
                "concepts": [],
                "key_points": [],
                "summary": "",
            }


class APIClient(LLMClient):
    """API 客户端 (OpenAI, Kimi, etc.)"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def extract_knowledge(self, text: str) -> dict:
        """调用 API 提取知识"""
        messages = [
            {
                "role": "system",
                "content": "你是一个知识提取助手。从讲座内容中提取结构化知识，以 JSON 格式返回。",
            },
            {
                "role": "user",
                "content": f"""从以下讲座内容中提取结构化知识：

{text[:3000]}

请提取：
1. 核心主题（一句话概括）
2. 关键概念（3-5个）
3. 重要知识点（列表形式）
4. 总结（100字以内）

以 JSON 格式返回：
{{
  "topic": "...",
  "concepts": ["...", "..."],
  "key_points": ["...", "..."],
  "summary": "..."
}}""",
            },
        ]

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json={"model": self.model, "messages": messages, "temperature": 0.3},
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()

            content = result["choices"][0]["message"]["content"]

            # 尝试解析 JSON
            try:
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(content[start:end])
            except Exception:
                pass

            return {
                "topic": "提取结果",
                "concepts": [],
                "key_points": [content[:500]],
                "summary": "",
            }

        except Exception as e:
            return {
                "topic": f"API 错误: {str(e)}",
                "concepts": [],
                "key_points": [],
                "summary": "",
            }


class LLMConfig:
    """LLM 配置"""

    # 预设配置
    PRESETS = {
        "ollama": {
            "name": "本地 Ollama",
            "base_url": "http://localhost:11434",
            "model": "llama2",
        },
        "kimi": {
            "name": "Kimi (Moonshot)",
            "base_url": "https://api.moonshot.cn/v1",
            "model": "moonshot-v1-8k",
        },
        "openai": {
            "name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-3.5-turbo",
        },
        "openrouter": {
            "name": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openrouter/moonshotai/kimi-k2.5",
        },
        "opencode": {
            "name": "OpenCode Zen",
            "base_url": "https://api.opencode.ai/v1",
            "model": "opencode/kimi-k2.5-free",
        },
    }

    @classmethod
    def create_client(
        cls, preset: str, api_key: Optional[str] = None, **kwargs
    ) -> LLMClient:
        """创建客户端"""
        if preset == "ollama":
            return OllamaClient(**kwargs)
        else:
            if not api_key:
                raise ValueError(f"{preset} 需要 API Key")
            config = cls.PRESETS.get(preset, cls.PRESETS["openai"])
            return APIClient(
                api_key=api_key,
                base_url=kwargs.get("base_url", config["base_url"]),
                model=kwargs.get("model", config["model"]),
            )
