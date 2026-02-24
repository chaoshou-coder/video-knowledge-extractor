# 使用说明（Usage Manual）

本文档覆盖从安装、配置到真实模型生产验证的全流程，便于单人排障和批量运行。

## 1. 安装与环境

- 推荐 Python 3.10+
- 推荐使用虚拟环境

```bash
python -m venv video-knowledge-extractor.venv
video-knowledge-extractor.venv\Scripts\Activate.ps1
python -m pip install -e .
```

如需 EPUB/HTML 导出能力：

```bash
python -m pip install -e ".[export]"
```

## 2. 配置

### 2.1 初始化

```bash
copy config.example.toml config.toml
```

### 2.2 配置示例

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

### 2.3 环境变量

- `KL_MODEL_API_KEY`：覆盖 `config.toml` 的 `model.api_key`
- `KL_APP_URL`：HTTP 头 `HTTP-Referer`
- `KL_APP_NAME`：HTTP 头 `X-Title`

## 3. CLI 总览

- `process`：处理单文件
- `batch`：处理目录，可并发、可重试
- `status`：查询本地处理状态（SQLite）
- `parse`：仅解析字幕
- `python kl.py`：Wizard 引导式交互

## 4. 命令示例

### 4.1 单文件（先 mock）

```bash
python kl.py process examples/sample1.srt --mock -o exports
```

### 4.2 批处理（先 mock）

```bash
python kl.py batch examples --mock --workers 2 -o exports
python kl.py batch examples --mock --build --format markdown -o exports
```

### 4.3 真实模型

```bash
python kl.py process examples/sample1.srt --config config.toml -o exports_prod
python kl.py batch examples --config config.toml --build --format markdown -o exports_prod
```

### 4.4 你刚才的生产示例

```bash
python kl.py batch "D:\Videos\dbd\test" --config config.toml --build --format markdown -o "E:\code\temp\video-knowledge-extractor\exports_prod\testexports"
```

### 4.5 失败重试

```bash
python kl.py batch examples --config config.toml --retry-from exports_prod\batch_report.json --build -o exports_prod_retry
```

## 5. 关键参数说明

- `--mock`：使用 `MockLLMClient`，不访问真实模型接口
- `--video-mark`：输出视频学习标记（字幕包含时间戳时有效）
- `-w, --workers`：目录并发 worker 数
- `-b, --build`：执行融合 + 聚类 + 导出
- `-f, --format`：`markdown|html|epub|all`
- `--retry-from`：读取历史 `batch_report.json` 的失败列表

## 6. 输出与结果

- 单文件：`_cleaned.md`、`_structured.md`
- 批处理：`cleaned/`、`structured/`、`batch_report.json`
- 教材构建：`--build` 后产出 markdown/html/epub

## 7. 排障清单

- `config.toml` 不存在：检查路径并执行复制模板
- 401/403：检查 API Key 与环境变量是否覆盖
- 批处理无文件：确认目录下有 `.srt` / `.txt`
- 重试无效：确认 `failed_files` 是否真实可访问
- PowerShell 参数写法：参数值不要加 `@` 前缀，例如 `--config config_grok.toml`
- `--video-mark` 是可选项，不是必须开启项

## 8. 最小验收

```bash
python kl.py parse examples/sample1.srt
python kl.py process examples/sample1.srt --mock -o exports_check
python kl.py batch examples --mock --build --format markdown -o exports_check
```

若以上 3 条通过，再进入真实模型与生产路径。
