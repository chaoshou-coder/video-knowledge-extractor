# 项目架构说明（CLI-only）

本文档描述 `video-knowledge-extractor` 的运行架构、核心模块职责、数据流和扩展点，帮助你在开发或投产前快速建立整体认知。

## 1. 设计目标

- **单入口 CLI**：统一通过命令行运行，避免 GUI/Web 分支带来的复杂度。
- **可自动化**：参数化命令适配脚本、CI、Agent 调用。
- **可观测**：使用 SQLite 追踪处理状态与知识点结果。
- **可降级**：LLM 不稳定时有回退策略，保证流程可继续。

## 2. 运行视图

系统只有两条主路径：

1. `process`：单文件处理（清洗 + 结构化，可选视频标记）
2. `batch`：目录并行处理；可选执行“融合 + 聚类 + 导出教材”

调用链路（简化）：

```text
kl / python kl.py
  -> src.cli
    -> _build_runtime()
      -> ProviderRegistry or MockLLMClient
      -> WorkflowEngine
    -> process / batch / status / parse
```

## 3. 模块职责

- `kl.py`
  - 轻量入口脚本，直接调用 `src.cli:main`。
- `src/cli.py`
  - 命令定义与参数解析（Click）。
  - 组织 `process`、`batch`、`status`、`parse` 与 Wizard 交互。
- `src/workflow.py`
  - 核心流水线：规则清理、语义分段、子切分、降噪、结构化提取、可选视频标记。
  - `ProgressTracker` 负责 SQLite 写入和状态追踪。
- `src/llm_provider.py`
  - 加载 `config.toml`。
  - 构造统一异步 LLM 客户端（OpenAI Chat Completions 兼容接口）。
  - 支持 OpenRouter provider 路由参数与环境变量覆盖。
- `src/parallel.py`
  - 批处理并行器（`asyncio.Semaphore` 限流）。
- `src/fusion.py`
  - 跨文档知识点去重与融合，生成章节衔接段落。
- `src/clustering.py`
  - 对融合后的知识点做主题聚类与课程结构构建。
- `src/export.py`
  - 导出 Markdown / HTML / EPUB。
- `src/srt_parser.py`
  - 解析标准 SRT 与时间戳 TXT。

## 4. 核心数据对象

定义位于 `src/workflow.py`：

- `Document`
  - 单个输入文件的处理单元，包含 `content`、`knowledge_points`、`metadata`。
- `KnowledgePoint`
  - 结构化知识点：`title`、`content`、`video_markers`、`source_file`。
- `SemanticSegment`
  - 语义分段结果（起止行、标题、内容）。
- `TextChunk`
  - 最终送入后续阶段的处理分块。

## 5. 流水线分阶段说明

`WorkflowEngine.process_document()` 的主阶段：

1. **rule_cleaning**：规则清理（正则去噪，无 LLM）
2. **semantic_segmentation**：LLM 通读并按行号语义分段
3. **sub_chunking**：按 `chunk_size` 做子切分，避免上下文超限
4. **noise_reduction**：对分块进行 LLM 清洗降噪
5. **structuring**：LLM 结构化提取知识点
6. **video_marking（可选）**：补充“需看视频画面”标记

每个阶段都记录耗时，写入 `doc.metadata["stage_durations"]`，并同步更新 SQLite 状态。

## 6. 存储与输出

### 6.1 SQLite（默认 `knowledge.db`）

- `documents`
  - 跟踪文档状态：`pending/processing/done` 与当前 `stage`。
- `knowledge_points`
  - 存储每个文档提取出的知识点与视频标记。

### 6.2 文件输出

- `process` 模式：
  - `<output>/<stem>_cleaned.md`
  - `<output>/<stem>_structured.md`
- `batch` 模式（split 目录）：
  - `<output>/cleaned/`
  - `<output>/structured/`
- `--build` 额外输出：
  - 教材文件：Markdown / HTML / EPUB（取决于 `--format`）

## 7. 配置系统

配置文件默认 `config.toml`：

- `[model]`
  - `api_base`、`api_key`、`model`、`timeout`
  - OpenRouter 扩展项（`provider_only` 等）
- `[processing]`
  - `chunk_size`

环境变量覆盖：

- `KL_MODEL_API_KEY`：覆盖配置中的 `api_key`
- `KL_APP_URL`、`KL_APP_NAME`：OpenRouter 请求头

## 8. 错误处理与降级

- LLM 网络抖动：内置有限重试。
- JSON 解析失败：尝试多种提取策略（代码块/裸 JSON/大括号截取）。
- 聚类或融合失败：降级到较保守策略（例如保留原知识点）。
- 语义分段失败：回退为“全文单段”处理。

## 9. 扩展建议

- **替换 LLM 后端**：实现 `TextGenerator` 协议（`generate()`）并注入 `WorkflowEngine`。
- **新增导出格式**：在 `TextbookExporter` 中添加导出方法并在 CLI 暴露选项。
- **优化并行策略**：调整 `batch --workers`，并按模型吞吐控制并发。
- **增强质量门禁**：在 CI 中补充更多 CLI 冒烟案例与输出校验。
