# video-knowledge-extractor

从 SRT/TXT 字幕自动生成结构化知识内容，并支持跨文件聚类、知识融合、教材导出与批量重试。

[![CI](https://github.com/chaoshou-coder/video-knowledge-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/chaoshou-coder/video-knowledge-extractor/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## 文档入口

- [快速生产指南](docs/MINIMAL_PROD_GUIDE.md)
- [详细使用手册](docs/USAGE.md)
- [技术架构](docs/ARCHITECTURE.md)
- [调试与问题排查](docs/DEBUG_AND_TEST_GUIDE.md)
- [项目贡献说明](docs/CONTRIBUTING.md)

---

## 这是什么

`video-knowledge-extractor` 是一个面向生产场景的 CLI 工具，目标是把课程/讲解字幕变成可复用的教材结构：

- 单文件与目录批量处理
- 结构化知识点抽取（LLM）
- 跨文件聚类与融合
- 视频时间段映射（可选）
- Markdown / HTML / EPUB 导出
- 批量失败文件重试与报告

项目默认不包含 Web UI / API Server，仅提供命令行和 Wizard 两种交互入口。

---

## 关键特性

- **两种运行模式**
  - `mock`：本地模拟，不触发外部 LLM。
  - 非 mock：通过 `config.toml` 使用 OpenAI 兼容接口。
- **可观测处理链路**
  - `process` 单文件执行；`batch` 目录并发执行。
  - SQLite 记录处理状态、阶段耗时与知识点落库。
- **可靠性**
  - 单文件失败不会中断整个批次。
- **可重跑**
  - 失败文件产出 `batch_report.json`，支持 `--retry-from` 精准重试。
- **可控性能**
- LLM 并发阈值、重试次数、chunk size 可配。

---

## 安装

### 1. 创建虚拟环境（推荐）

```bash
python -m venv video-knowledge-extractor.venv
video-knowledge-extractor.venv\Scripts\Activate.ps1
```

### 2. 安装本项目

```bash
python -m pip install -e .
```

如需 EPUB 导出依赖：

```bash
python -m pip install -e ".[export]"
```

---

## 配置

1. 复制配置模板：

```bash
copy config.example.toml config.toml
```

2. 至少保证以下字段存在（示例）：

```toml
[model]
api_base = "https://openrouter.ai/api/v1"
api_key = "sk-or-your-api-key"
model = "google/gemini-2.5-flash-lite"
timeout = 300

[processing]
chunk_size = 60000
max_retries = 3
max_llm_concurrency = 8
```

3. 常用覆盖方式：

- `KL_MODEL_API_KEY`：覆盖 `model.api_key`
- `KL_APP_URL`：OpenRouter `HTTP-Referer`
- `KL_APP_NAME`：OpenRouter `X-Title`

> 安全建议：不要把真实密钥长期提交到仓库，可优先用环境变量注入。

---

## 快速上手

### 验证 CLI 可用

```bash
python kl.py --help
```

### Mock 验证（不调 API）

```bash
python kl.py process examples/sample1.srt --mock -o exports
python kl.py batch examples --mock --build --format markdown -o exports
```

### 真实模型验证

```bash
python kl.py process examples/sample1.srt --config config.toml -o exports_prod
python kl.py batch examples --config config.toml --build --format markdown -o exports_prod
```

---

## CLI 概览

- `process`：处理单文件
- `batch`：批处理目录（支持 `--workers`, `--build`, `--format`, `--retry-from`）
- `status`：查看最近处理记录（SQLite）
- `parse`：仅解析字幕，便于查看解析效果
- 无参数直接运行：Wizard 模式（交互式向导）

详细命令参数见 [docs/USAGE.md](docs/USAGE.md)。

---

## 输出产物

- `process`：`<output>/<stem>_cleaned.md`、`<output>/<stem>_structured.md`
- `batch`（不建 split）：同上按文件输出
- `batch`（split 目录）：`<output>/cleaned/`、`<output>/structured/`
- `--build`：教材文件（markdown/html/epub）
- `batch` 会额外生成：`<output>/batch_report.json`

---

## 常见问题

- `config.toml` 找不到：先执行 `copy config.example.toml config.toml`
- `401/403`：检查 key 是否正确，是否被环境变量覆盖
- 批处理无文件：确认目录下有 `.srt` 或 `.txt`
- OpenRouter 路由异常：确认 provider 选项与 `provider_allow_fallbacks` 配置

---

## 许可证

MIT License，详见 [LICENSE](./LICENSE)。

