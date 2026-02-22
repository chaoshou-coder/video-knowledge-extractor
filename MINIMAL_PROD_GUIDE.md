# 最小可投产使用说明（ASAP）

本说明只覆盖上线必需路径：`配置 -> 跑通示例 -> 切换真实模型 -> 批量导出 Markdown`。

## 1) 安装

```bash
python -m pip install -e .
```

## 2) 配置模型（单模型基建）

复制模板：

```bash
cp config.example.toml config.toml
```

编辑 `config.toml`，填写模型参数（`api_base` / `api_key` / `model`）：

```toml
[model]
api_base = "https://openrouter.ai/api/v1"
api_key = "sk-or-your-api-key"
model = "openai/gpt-4.1-nano"
timeout = 300

# OpenRouter provider 路由（可选）
# provider_only = ["azure"]
# provider_order = ["azure"]
# provider_allow_fallbacks = false

[processing]
chunk_size = 60000
```

说明：
- 统一只用一个模型配置，核心业务与具体厂商松耦合。
- 可用环境变量覆盖 key：`KL_MODEL_API_KEY`。
- `chunk_size` 是 token 数，建议对齐模型 output limit。

## 3) 用 examples 做最小验收（推荐先 mock）

项目示例数据：
- `examples/sample1.srt`
- `examples/sample2.txt`

先跑 mock（不调用真实 API）：

```bash
python kl.py process examples/sample1.srt --mock -o exports
python kl.py process examples/sample2.txt --mock -o exports
python kl.py batch examples --mock --build --format markdown -o exports
```

验收标准：
- 三条命令都成功退出；
- `exports/` 下生成 `_cleaned.md` 和 `_structured.md`；
- batch 模式下输出落在 `exports/cleaned/` 与 `exports/structured/`；
- 控制台显示阶段耗时、总耗时和知识点统计。

## 4) 切换真实模型运行

```bash
python kl.py process examples/sample1.srt --config config.toml -o exports_prod
python kl.py batch examples --config config.toml --build --format markdown -o exports_prod
```

可选打开视频标记阶段（默认关闭）：

```bash
python kl.py batch examples --config config.toml --build --format markdown -o exports_prod --video-mark
```

## 5) 交互式 Wizard（人类临时使用）

无参数启动即进入引导式交互：

```bash
python kl.py
```

有参数时走非交互命令模式（更适合 LLM/自动化调用）。

## 6) 最小故障排查

- `未找到配置文件 config.toml`：先复制 `config.example.toml` 并填写。
- `401/403`：检查 `api_key` 是否有效，或是否被环境变量覆盖成错误值。
- OpenRouter provider 未生效：确认配置了 `provider_only`，并配套 `provider_allow_fallbacks = false`。
- `批量处理 0 个文件`：确认目录下存在 `.srt` 或 `.txt`。
