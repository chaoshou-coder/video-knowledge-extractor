# Video Knowledge Extractor

从视频字幕（SRT/TXT）提取结构化知识并导出教材内容的 CLI 工具。

[![CI](https://github.com/chaoshou-coder/video-knowledge-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/chaoshou-coder/video-knowledge-extractor/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

文档导航：

- 快速上手：[`docs/MINIMAL_PROD_GUIDE.md`](./docs/MINIMAL_PROD_GUIDE.md)
- 详细使用说明：[`docs/USAGE.md`](./docs/USAGE.md)
- 架构设计说明：[`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)

---

## 项目状态

- 运行形态：**CLI-only**（仅终端交互，支持参数模式 + Wizard 模式）
- 已移除：桌面 GUI、Web UI/API 入口
- 核心能力：单文件处理、批处理、跨文档聚类、知识融合、Markdown/HTML/EPUB 导出

---

## 功能特性

- 字幕解析：支持标准 `SRT` 和时间戳 `TXT`
- 智能清洗：规则清理 + LLM 语义分段/子切分/降噪
- 结构化提取：LLM 提取知识点并合并去重
- 批处理流水线：并行处理 + 聚类 + 融合 + 导出
- OpenRouter 路由：支持 `provider_only / provider_order / provider_allow_fallbacks` 等策略

---

## 安装

```bash
python -m pip install -e .
```

如需导出 EPUB/HTML 相关依赖，可安装：

```bash
python -m pip install -e ".[export]"
```

安装后可直接使用：

```bash
kl --help
```

也可用项目入口脚本：

```bash
python kl.py --help
```

---

## 配置

复制模板并填写模型配置：

```bash
# Linux/macOS
cp config.example.toml config.toml

# Windows PowerShell
copy config.example.toml config.toml
```

`config.toml` 示例：

```toml
[model]
api_base = "https://openrouter.ai/api/v1"
api_key = "sk-or-your-api-key"
model = "google/gemini-2.5-flash-lite"
timeout = 300

# OpenRouter provider 路由（可选）
# provider_only = ["azure"]
# provider_order = ["azure"]
# provider_allow_fallbacks = false
# provider_ignore = ["anthropic"]
# provider_require_parameters = true
# provider_data_collection = "deny"
# provider_zdr = true
# provider_sort = "throughput"

[processing]
chunk_size = 60000
max_retries = 3
max_llm_concurrency = 8
```

环境变量：

- `KL_MODEL_API_KEY`：可覆盖 `config.toml` 的 `model.api_key`
- `KL_APP_URL`：OpenRouter 请求头 `HTTP-Referer`（可选）
- `KL_APP_NAME`：OpenRouter 请求头 `X-Title`（可选）

---

## 快速开始

### 1) 单文件处理（mock）

```bash
python kl.py process examples/sample1.srt --mock -o exports
python kl.py process examples/sample2.txt --mock -o exports
```

### 2) 批处理（mock）

```bash
python kl.py batch examples --mock --workers 2 -o exports
python kl.py batch examples --mock --build --format markdown -o exports
```

### 3) 真实模型

```bash
python kl.py process examples/sample1.srt --config config.toml -o exports_prod
python kl.py batch examples --config config.toml --build --format markdown -o exports_prod
```

---

## CLI 命令

### `process` 处理单文件

```bash
kl process [OPTIONS] FILE_PATH
```

选项：

- `--config`：LLM 配置文件（默认 `config.toml`）
- `--mock`：模拟模式，不调用外部 API
- `--video-mark`：启用视频标记阶段（额外 LLM 调用）
- `-o, --output`：输出目录（默认 `./exports`）

### `batch` 批处理目录

```bash
kl batch [OPTIONS] DIRECTORY
```

选项：

- `-w, --workers`：并行处理数（默认 `3`）
- `-b, --build`：执行聚类/融合/导出全流水线
- `-f, --format`：导出格式 `markdown|epub|html|all`（默认 `markdown`）
- `-o, --output`：输出目录（默认 `./exports`）
- `--config`：LLM 配置文件（默认 `config.toml`）
- `--retry-from`：基于上一轮 `batch_report.json` 仅重试失败文件
- `--mock`：模拟模式，不调用外部 API
- `--video-mark`：启用视频标记阶段

### `status` 查看处理状态

```bash
kl status
```

### `parse` 仅解析字幕

```bash
kl parse examples/sample1.srt
kl parse examples/sample2.txt
```

### Wizard 模式

不带子命令直接运行即进入引导式交互：

```bash
python kl.py
```

---

## 输出说明

### `process` 模式

- 清洗输出：`<output>/<stem>_cleaned.md`
- 结构化输出：`<output>/<stem>_structured.md`

### `batch` 模式

- 清洗输出目录：`<output>/cleaned/`
- 结构化输出目录：`<output>/structured/`
- 如开启 `--build`，还会输出教材文件（按 `--format`）
- 每次批处理会生成：`<output>/batch_report.json`（成功/失败/跳过明细）
- 导出的 Markdown/HTML 目录支持超链接直达章节

---

## 批处理与重试

- 批处理在单文件失败时不会拖垮整批：失败文件会记录到报告，其他文件继续。
- 可用 `--retry-from` 只重跑失败文件：

```bash
kl batch examples --config config.toml --retry-from exports_prod/batch_report.json -o exports_prod_retry
```
- 按 `Ctrl+C` 时会停止接收新文件，等待当前正在处理的任务完成后再退出。

---

## 处理流程（核心业务）

1. 规则清理（无 LLM）
2. LLM 通读全文并做语义分段
3. 超限段落按 `chunk_size` 做子切分
4. 对最终分块做 LLM 清洗降噪
5. 拼接并保存清洗结果（`_cleaned.md`，含分块策略）
6. 对清洗块做 LLM 结构化提取
7. 合并并保存结构化结果（`_structured.md`）
8. 可选：视频标记阶段（`--video-mark`）

---

## 开发与验证

本地最小检查：

```bash
python -m compileall src kl.py
ruff check src/
python kl.py parse examples/sample1.srt
python kl.py process examples/sample1.srt --mock -o exports_check
python kl.py process examples/sample2.txt --mock -o exports_check
python kl.py batch examples --mock --workers 2 -o exports_check
python kl.py batch examples --mock --build --format markdown -o exports_check
```

CI 当前执行：

- CLI 冒烟：`process sample1.srt` + `process sample2.txt`（mock）
- 代码检查：`ruff check src/`

---

## 常见问题

- `未找到配置文件 config.toml`：先从 `config.example.toml` 复制
- `401/403`：检查 `api_key` 或 `KL_MODEL_API_KEY`
- OpenRouter 路由未生效：确认 `provider_only` + `provider_allow_fallbacks = false`
- 批处理未发现文件：确认目录下存在 `.srt` 或 `.txt`

---

## 许可

[MIT License](./LICENSE)

## 贡献

见 [`docs/CONTRIBUTING.md`](./docs/CONTRIBUTING.md)。
 

