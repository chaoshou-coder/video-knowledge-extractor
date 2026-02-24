# 技术架构说明（video-knowledge-extractor）

本文档给出从输入到产物的技术架构，重点覆盖：
- 处理链路边界
- 关键质量防线（防静默质量退化）
- 监控与可复查能力

## 1. 系统边界与职责

### 1.1 职能边界
- 仅处理 `.srt`/`.txt` 字幕文本，不做语音转写（ASR）：
  - 输入：本地文件（process）或目录（batch）
  - 输出：清洗/结构化结果、教材导出文件、批次报告
- CLI 为默认交互方式，不提供 Web/API 服务。
- 支持两种运行模式：
  - `--mock`：本地 MockLLMClient，不访问外部 LLM
  - 真实模型：按 `config.toml` 配置 OpenAI 兼容接口

### 1.2 非功能目标
- 可批量稳定运行（单文件失败不影响整批）
- 可重跑（失败文件可从 `batch_report.json` 重试）
- 可观测：日志 + metadata + sqlite + report
- 可维护：结构化链路有可复用治理点（提示词、质量门禁、重试、fallback）

## 2. 运行模型（process / batch）

```text
用户命令
  └─ python kl.py ...
      └─ src/cli.py
          ├─ 参数与子命令解析（process / batch / parse / status）
          ├─ 配置加载与运行时组装（ProviderRegistry / WorkflowEngine / tracker）
          ├─ 分支 1: process
          │     └─ workflow.process_document（单文件）
          └─ 分支 2: batch
                ├─ parallel.py 文件并发调度（workers）
                ├─ workflow.process_document（按文件循环）
                ├─ batch_report 汇总
                ├─ build（可选）：fusion -> clustering -> export
                └─ 输出产物（cleaned / structured / textbook / report）
```

## 3. 核心模块职责

- `kl.py`
  - 项目入口脚本，透传到 `src.cli:main`。
- `src/cli.py`
  - 命令树与参数解析
  - 配置读取、运行时创建与关闭
  - `--retry-from` 解析与批次报告落盘
  - 打印模型与并发运行时摘要（含 `response_format`）
- `src/workflow.py`（核心）
  - 单文件流水线编排
  - 阶段：
    1) `rule_cleaning`（规则清理）
    2) `sub_chunking`（切分）
    3) `structuring`（结构化）
    4) `video_marking`（可选）
  - 结构化阶段包括：
    - `prompt` 工程化
    - JSON 解析与标准化
    - 质量门禁
    - 低质重试
    - 受控 fallback
    - 输出去重（`title::content`）与元信息打点
- `src/llm_provider.py`
  - `ModelConfig / LLMProvider / ProviderRegistry`
  - OpenAI-style Chat Completions 调用、重试与超时控制
  - `response_format` 配置透传（如 `json_object`）
  - `MockLLMClient` 支持离线回归
- `src/srt_parser.py`
  - SRT/TXT 解析为字幕条目
  - 提供时间戳元数据，供视频标记与 time_ranges 使用
- `src/parallel.py`
  - 文件级并发调度与中断控制（`Processor`）
  - 聚合每个文件的处理摘要供 batch_report 使用
- `src/fusion.py`
  - 基于相似度规则去重与合并知识点
- `src/clustering.py`
  - 将知识点聚类为课程章节结构
- `src/export.py`
  - markdown/html/epub 导出器
- `src/workflow_monitor.py`
  - 当前未作为主链路强制依赖，保留为未来可观测增强点

## 4. 结构化防退化架构（本次重点）

结构化是系统关键风险区，当前版本采用“三层防线”：

### 4.1 第一层：提示词工程（contract）
- `src/workflow.py::_build_structure_prompt`
  - 角色定义（课程结构化标注员）
  - 固定输出对象 `{"points":[...]}`
- 字段约束：
  - `title`：非空、非占位词、长度上限约束
  - `content`：按 chunk 长度动态最小长度
  - `evidence`：至少 1 条
  - `time_ranges`：有时间戳时可输出映射
- 约束语义：
  - 禁止只给一句话
  - 禁止过度口号化表达
  - 禁止合并多个主题为一条
- 额外防误导：
  - 反例/示例并存
  - 二次精提模式 `is_refinement=True` 提供更严格要求

### 4.2 第二层：质量门禁（quality gate）
- `src/workflow.py::_validate_structure_points`
- 检查项：
  - points 数量
  - title 合规性（非空/非占位）
  - content 字符长度
  - evidence 不为空
  - 有时间戳时 time_ranges 不为空
- 不通过时进入二次处理分支，而非静默落盘

### 4.3 第三层：低质重试 + 受控回退
- `_stage_structure_single_pass`
  - 若首轮失败：换更细颗粒提示词重试一次
  - 若重试仍失败：fallback 到可追踪版本
- `fallback` 行为：
  - 不再硬编码 `未命名知识点`
  - 从证据、正文前段、时间区间生成可读标题
  - 产出“受控降级”内容，防止原文整段 dump

### 4.4 可追溯指标
- `workflow.process_document` 落盘 metadata：
  - `structure_retry_count`
  - `structure_fallback_count`
  - `structure_weak_chunk_count`
  - `estimated_time_range_count`
- 可通过日志定位到具体 chunk 编号与问题点

## 5. 数据与持久化

- SQLite：`knowledge.db`
  - `documents`：文件级状态、阶段、错误信息与耗时
  - `knowledge_points`：知识点正文、视频标记、来源文件
- 批次报告：`batch_report.json`
  - 完整成功/失败/跳过明细
  - 支持失败文件重跑
- 文件产物：
  - 单文件：`*_cleaned.md` / `*_structured.md`
  - 批处理：`cleaned/` / `structured/` 目录
  - build：教材格式输出（markdown/html/epub）+ batch_report

## 6. 错误处理与重试策略

- 文件级失败隔离，不阻断整批
- 两级重试：
  - 接口级：`max_retries`
  - 结构化质量重试：弱质量二次提取
- 失败时：
  - 记录 `DocumentProcessingError` 的阶段与明细
  - batch 总结失败列表并生成 report，可通过 `--retry-from` 精准重放

## 7. 并发与性能控制

- `batch --workers`：文件并发
- `processing.max_llm_concurrency`：LLM 全局并发闸门
- `processing.chunk_size`：切块长度，影响切分效率与结构化颗粒度
- `processing.max_retries`：模型接口重试次数
- 推荐先从保守并发启动，再按 API 报错率/耗时曲线扩容

## 8. 扩展与演进

- 更换/新增模型供应商：通过 `model` 配置和兼容 `TextGenerator.generate` 协议接入
- 增加导出格式：扩展 `src/export.py` 并补充 CLI `--format` 校验
- 更深观测：引入错误码分级、链路指标告警、A/B prompt 对账
- 更完整降级策略：按内容退化类型定义更细的重试/替换规则

## 9. 文档导航核对

- `README.md`：项目概览与快速上手入口
- `docs/USAGE.md`：命令、参数、最小验收、故障排查
- `docs/USAGE.md`：补充排查与诊断建议
- `docs/CONTRIBUTING.md`：贡献与提交规范

