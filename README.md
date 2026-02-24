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

> 推荐阅读顺序：先 `USAGE.md`（确定命令边界），再 `ARCHITECTURE.md`（理解结构化防线），最后 `USAGE.md` 的“排障清单”章节（问题定位）。

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
- **结构化可控性**
  - 结构化提示词升级为“角色-契约-反例-样例”框架
  - 质量门禁 + 低质重试 + 受控 fallback
  - 降低“空 title / 内容过短 / JSON 解析失败”导致的静默污染
- **可靠性**
  - 单文件失败不会中断整个批次。
- **可重跑**
  - 失败文件产出 `batch_report.json`，支持 `--retry-from` 精准重试。
- **可控性能**
- LLM 并发阈值、重试次数、chunk size 可配。

### 结构化能力说明（重点）

结构化阶段采用三层防线，确保知识点生成具备可控性与可追溯性：

1. 提示词契约化：固定 JSON 输出契约，要求 `title/content/evidence/time_ranges` 均满足结构与内容约束。  
2. 质量门禁：对 `title` 非空、文本长度、证据完整性、时间戳映射等维度做校验。  
3. 异常兜底：弱质量先重试（精提模式），若仍不合格则进入受控 fallback，生成可读标题并记录降级指标。

对应实现位点：

- `src/workflow.py::_build_structure_prompt`：提示词与结构约束  
- `src/workflow.py::_validate_structure_points`：质量门禁规则  
- `src/workflow.py::_stage_structure_single_pass`：重试 + fallback 编排  
- `src/workflow.py::_parse_json_response`：响应解析失败即上抛错误  
- `src/workflow.py::_build_fallback_points`：受控降级标题与内容生成

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
response_format = { type = "json_object" }

[processing]
chunk_size = 60000
max_retries = 3
max_llm_concurrency = 8
```

3. 常用覆盖方式：

- `KL_MODEL_API_KEY`：覆盖 `model.api_key`
- `KL_APP_URL`：OpenRouter `HTTP-Referer`
- `KL_APP_NAME`：OpenRouter `X-Title`
- `response_format`（可选）：强烈建议配置 `json_object`，用于约束结构化输出
- `response_format` 支持两种写法：
  - `response_format = { type = "json_object" }`
  - `response_format = "json_object"`

> `response_format` 是可选项，若模型/网关不支持可直接移除该配置行，主流程仍可运行。

> 安全建议：不要把真实密钥长期提交到仓库，可优先用环境变量注入。

### 推荐运维参数（生产经验）

- `chunk_size`：越大越省 LLM 调用次数，但单 chunk 过长可能增加 `points` 欠拆风险
- `max_retries`：接口级重试（429/5xx/网络异常）
- `max_llm_concurrency`：根据 API 配额控制并发
- 若仍有大量 `fallback`，可先从 `response_format` 入手，再回看 `chunk_size` 与提示词长度

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

结构化指标示例（`python` 直接读取）：

```json
{
  "has_timestamps": true,
  "structure_retry_count": 1,
  "structure_fallback_count": 0,
  "structure_weak_chunk_count": 0,
  "estimated_time_range_count": 3
}
```

---

## 常见问题

- `config.toml` 找不到：先执行 `copy config.example.toml config.toml`
- `401/403`：检查 key 是否正确，是否被环境变量覆盖
- 批处理无文件：确认目录下有 `.srt` 或 `.txt`
- OpenRouter 路由异常：确认 provider 选项与 `provider_allow_fallbacks` 配置

---

## 许可证

MIT License，详见 [LICENSE](./LICENSE)。

