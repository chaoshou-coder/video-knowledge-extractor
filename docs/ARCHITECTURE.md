# 技术架构说明（video-knowledge-extractor）

本文件描述 `video-knowledge-extractor` 的模块边界、执行流、持久化与扩展点，目标是让你在不翻代码的情况下先建立全局认知。

## 1. 设计边界

- 职能边界
  - 提供 CLI 与 Wizard 两种交互入口，默认不提供 Web/API。
  - 输入限定为字幕文本文件（`.srt` 或 `.txt`），不负责语音转写。
  - 聚焦“从字幕到知识输出产物”的生产化流水线。
- 非功能目标
  - 批量运行稳定、可重试、可复盘。
  - 输出 Markdown/HTML/EPUB 与课堂学习标记。
  - 支持 mock 与真实模型并行回归。

## 2. 运行模型（Single Pass + Batch）

```text
CLI (python kl.py / kl)
    └─ src/cli.py
        ├─ 参数与子命令解析
        ├─ 运行时构建（LLM 客户端 + WorkflowEngine）
        ├─ 进度与重试上下文（SQLite）
        └─ 选择执行路径
            ├─ process（单文件）
            └─ batch（目录）
                 ├─ 并发调度（parallel.py）
                 ├─ process_document（workflow.py）
                 ├─ batch_report 汇总
                 ├─ build（可选）
                 │   ├─ 融合（fusion.py）
                 │   ├─ 聚类（clustering.py）
                 │   └─ 导出（export.py）
                 └─ 输出文件与报告
```

## 3. 模块职责

- `kl.py`
  - 项目脚本入口，转发到 `src.cli:main`，确保 `python kl.py` 与 `kl` 统一入口行为。
- `src/cli.py`
  - `process / batch / status / parse` 四类命令与通用参数解析。
  - 加载配置并组装运行时（TextGenerator + WorkflowEngine）。
  - 管理批次报告落盘与 `--retry-from` 解析。
- `src/workflow.py`
  - 核心流水线引擎。
  - 阶段：
    - `rule_cleaning` 规则清洗
    - `sub_chunking` 上下文切块
    - `noise_reduction` （降噪清洗）
    - `structuring`（知识点抽取）
    - `video_marking`（可选时间戳标记）
  - 通过 `ProgressTracker` 写入/更新 `knowledge.db`。
- `src/llm_provider.py`
  - 统一构造异步 LLM 客户端，兼容 OpenAI Chat Completions 风格接口。
  - 处理 `model` 与 `processing` 配置，统一重试、超时与并发闸门。
  - 提供 `MockLLMClient`，支持离线回归。
- `src/parallel.py`
  - 文件级并发调度器，限制 worker 数，失败隔离并汇总结果。
- `src/fusion.py`
  - 跨文档知识点去重与融合。
- `src/clustering.py`
  - 知识点主题聚类与课程章节构建。
- `src/export.py`
  - 输出 Markdown/HTML/EPUB，负责目录与内容拼装。
- `src/srt_parser.py`
  - 解析 SRT/时间戳 TXT，保留时间索引供视频映射。
- `src/workflow_monitor.py`
  - 实验性日志监控模块，当前非主路径硬依赖。

## 4. 状态与数据持久化

- SQLite 文件：`knowledge.db`（默认）  
  - `documents`: 文件状态、当前阶段、错误码/错误信息、时间记录。
  - `knowledge_points`: 每条知识点文本与来源文件上下文。
- 文件产物
  - `process`：`<output>/<stem>_cleaned.md`、`<output>/<stem>_structured.md`
  - `batch`：`<output>/cleaned/`、`<output>/structured/`
  - `--build`：课程文本（markdown/html/epub）
  - `batch_report.json`：本次批次成功/失败/跳过明细

## 5. 错误处理与重试

- 文件级失败不阻断整批。
- 失败写入 `batch_report.json`，用于后续精准重跑。
- 重试文件解析时兼容：
  - `failed_files` 为字符串路径；
  - `failed_files` 为对象，使用 `{"path": ...}`。
- 路径解析策略：优先按当前运行环境解析，再回退到 report 所在目录。

## 6. 并发策略

- `batch --workers` 控制并发文件数。
- `max_llm_concurrency` 控制全局 LLM 请求并发上限。
- `max_retries` 控制可用重试次数（429/5xx 等场景）。
- 建议在生产端先从保守并发开始，再按模型限流与CPU/内存曲线递增。

## 7. 扩展路线

- 更换模型厂商：实现兼容同一 `generate` 协议的客户端并通过 `model` 配置路由。
- 新增导出格式：在 `export.py` 新增 formatter 并扩展 CLI `--format` 约束。
- 强化观测性：将阶段耗时、失败码、重试次数纳入日志告警。
- 改造重试策略：按错误类型（速率限制 / 内容异常 / 提示词异常）分级处理。

