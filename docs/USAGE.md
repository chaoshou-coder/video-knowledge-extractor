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
response_format = { type = "json_object" }

[processing]
chunk_size = 60000
max_retries = 3
max_llm_concurrency = 8
```

### 2.3 环境变量

- `KL_MODEL_API_KEY`：覆盖 `config.toml` 的 `model.api_key`
- `KL_APP_URL`：HTTP 头 `HTTP-Referer`
- `KL_APP_NAME`：HTTP 头 `X-Title`

### 2.4 结构化 JSON 约束（可选强化）

- 可选项：`response_format`
- 建议值：`{ type = "json_object" }`
- 作用：在支持该参数的供应商上，要求模型以标准 JSON 返回，减少“看起来像 JSON 但无法解析”的边界输入。

示例：

```toml
[model]
api_base = "https://openrouter.ai/api/v1"
api_key = "sk-or-your-api-key"
model = "google/gemini-2.5-flash-lite"
timeout = 300
response_format = { type = "json_object" }
```

如果模型或网关不支持 `response_format`，可以直接删除该配置项并保留 `points`/`content` 约束链路。

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

### 4.4 生产验证示例（历史环境）

```bash
python kl.py batch "D:\Videos\dbd\test" --config config.toml --build --format markdown -o "E:\code\temp\video-knowledge-extractor\exports_prod\testexports"
```

完整生产命令（本次回归使用）：

```bash
python kl.py batch "D:\Videos\dbd\" --workers 2 --build --video-mark --format markdown --output "E:\code\temp\video-knowledge-extractor\exports_prod" --config "E:\code\temp\video-knowledge-extractor\config.toml"
```

> 在修改代码后，建议执行：
> `python -m pip install -e .`（在虚拟环境内）后再跑该命令。

### 4.5 失败重试

```bash
python kl.py batch examples --config config.toml --retry-from exports_prod\batch_report.json --build -o exports_prod_retry
```

## 5. 结构化能力

该能力默认开启，面向日常使用者的核心认知是：

- 结构化输出会按稳定格式产出知识点
- 当质量异常时会触发重试并可回退，不会直接静默成功
- 处理日志会保留重试、降级与时间映射相关指标，便于排障

若需深入理解实现细节，可查看：

- [docs/ARCHITECTURE.md](ARCHITECTURE.md) 的“结构化防退化架构”
- [src/workflow.py](src/workflow.py) 的结构化相关函数

### 5.1 运维可见指标（最小集合）

出现结构化质量问题时，请关注以下字段：

- `structure_retry_count`：弱质量触发重试次数
- `structure_fallback_count`：fallback 次数
- `structure_weak_chunk_count`：弱质量 chunk 数
- `estimated_time_range_count`：估算时间段数量

这几个字段会写入文档 metadata 与 `batch_report.json`，用于批次复盘。

## 6. 关键参数说明

- `--mock`：使用 `MockLLMClient`，不访问真实模型接口
- `--video-mark`：输出视频学习标记（字幕包含时间戳时有效）
- `-w, --workers`：目录并发 worker 数
- `-b, --build`：执行融合 + 聚类 + 导出
- `-f, --format`：`markdown|html|epub|all`
- `--retry-from`：读取历史 `batch_report.json` 的失败列表
- `response_format`：在 `config.toml` 配置中声明，默认可选；建议在支持的后端配置 `json_object`
- `--output`：结构化/教材产物目录

## 7. 输出与结果

- 单文件：`_cleaned.md`、`_structured.md`
- 批处理：`cleaned/`、`structured/`、`batch_report.json`
- 教材构建：`--build` 后产出 markdown/html/epub
  - `batch_report.json` 包含每个文件状态、失败摘要、未分配章节等

## 8. 排障清单

- `config.toml` 不存在：检查路径并执行复制模板
- 401/403：检查 API Key 与环境变量是否覆盖
- 批处理无文件：确认目录下有 `.srt` / `.txt`
- 重试无效：确认 `failed_files` 是否真实可访问
- PowerShell 参数写法：参数值不要加 `@` 前缀，例如 `--config config_grok.toml`
- `--video-mark` 是可选项，不是必须开启项
- 结果偏口语化（过短）时：
  - 先确认 `response_format` 是否生效
  - 查看是否触发重试和 fallback（日志会标注 chunk 编号）
  - 检查 `structure_retry_count`、`structure_fallback_count` 是否异常偏高
- 仍出现 `未命名` 类标题：
  - 优先核验 `response_format` 与 `chunk_size` 配置
  - 检查该文件是否频繁触发 fallback，可参考 `docs/DEBUG_AND_TEST_GUIDE.md`
- 出现“内容很短 + 时间戳很多”（教材看起来像目录）：
  - 查看 `exports/check/` 下对应 `*_cleaned.md` 的 `最终处理分块数`
  - 若是字幕文件且该数值为 `1`，通常说明 `chunk_size` 过大（如 1000000）
  - 建议先调小 `chunk_size` 至 10000~60000 并重跑批处理

## 9. 最小验收

```bash
python kl.py parse examples/sample1.srt
python kl.py process examples/sample1.srt --mock -o exports_check
python kl.py batch examples --mock --build --format markdown -o exports_check
```

若以上 3 条通过，再进入真实模型与生产路径。

### 9.1 结构化回归验收点（建议）

```bash
python kl.py process examples/sample1.srt --mock -o exports_check
python kl.py batch examples --mock --workers 2 --build --format markdown -o exports_check
```

检查要点：

- `exports_check/*_structured.md` 中不出现 `"未命名知识点"` 这种硬编码兜底标题
- 文件中 `content` 长度显著高于极简口号化文本
- `batch_report.json` 能完整生成，且失败条目可复现可重试

