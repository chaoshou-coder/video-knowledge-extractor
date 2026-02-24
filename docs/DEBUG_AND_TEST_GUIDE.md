# 调试与运维手册

本文档用于快速接手运行、定位故障与交接运维。

## 1. 文档用途

本手册目标：
- 在最短时间内理解项目运行边界
- 完成标准化的 mock 与真实环境验收
- 建立故障定位闭环（从现象到修复）
- 形成可交接的运维记录

该内容与 `docs/USAGE.md` 的以下章节保持一致：
- `5` 结构化链路与防护机制
- `6` 关键参数说明
- `8` 排障清单
- `9` 最小验收

## 2. 第一次接手：环境与最小运行

### 2.1 环境准备

```bash
python -m venv video-knowledge-extractor.venv
video-knowledge-extractor.venv\Scripts\Activate.ps1
python -m pip install -e .
```

如果需要 EPUB/HTML 导出能力：

```bash
python -m pip install -e ".[export]"
```

### 2.2 先跑一次最小回归（推荐）

```bash
python kl.py parse examples/sample1.srt
python kl.py process examples/sample1.srt --mock -o exports_check
python kl.py batch examples --mock --build --format markdown -o exports_check
```

以上通过后再进入真实模型环境，避免将环境问题与模型问题混淆。

## 3. 生产运维流程

### 3.1 固定生产命令

```bash
python kl.py batch "D:\Videos\dbd\" --workers 2 --build --video-mark --format markdown --output "E:\code\temp\video-knowledge-extractor\exports_prod" --config "E:\code\temp\video-knowledge-extractor\config.toml"
```

代码变更后执行：

```bash
python -m pip install -e .
```

再复跑生产命令，确保可复现。

### 3.2 失败文件的标准重跑

```bash
python kl.py batch examples --config config.toml --retry-from exports_prod\batch_report.json --build -o exports_prod_retry
```

## 4. 结构化健康检查（优先级最高）

查看 `batch_report.json` 和日志的结构化指标：

- `structure_retry_count`：弱质量触发重试次数
- `structure_fallback_count`：fallback 次数
- `structure_weak_chunk_count`：弱质量 chunk 数
- `estimated_time_range_count`：估算时间段数量

判定建议：
- 指标持续上升：先回看 `chunk_size` 与 `processing.max_retries`
- `fallback` 频繁：检查分片文本噪声比例、时间戳完整性、提示词一致性
- 结构化内容异常短：重点核验 `response_format` 生效与输入 chunk 长度

## 5. 排障决策树（可直接执行）

1. 文件处理失败 / 无输出  
   - 校验 `config.toml` 与路径权限  
   - 校验 API Key 是否有效、是否被环境变量覆盖  
   - 查看 `--retry-from` 对应的失败列表是否可访问

2. 结构化结果可读性差  
   - 检查 chunk 划分是否过大或过小  
   - 检查日志是否显示大量 fallback

3. 视频标记缺失  
   - 确认输入字幕包含可解析时间戳  
   - 确认执行命令携带 `--video-mark`

4. 重跑后仍不稳定  
   - 对比两次 `batch_report.json` 的差异  
   - 将差异文件归档到交接记录

## 6. 交接与运维留档（每次发布必须）

- 记录运行版本号与提交 hash
- 记录 `config.toml`（脱敏）
- 保存 `batch_report.json` 与失败文件路径
- 记录关键指标基线（`structure_*`）
- 保存用于复现的命令清单（含 mock 与真实环境）

交接时以“5 分钟复现实验”为准：一位新成员在新环境按命令链路能在有限时间内复现核心结果，即可视为接手完成。
# 调试与问题排查指南



## 1. 与排障入口

同内容也同步维护在 `docs/USAGE.md` 的 `结构化` 及 `最小验收` 章节：

- `## 5` 结构化链路与防护机制（默认已内置）
- `## 8` 排障清单
- `## 9` 最小验收

## 2. 常见问题（先看这 5 条）

- `config.toml` 不存在：先复制模板 `copy config.example.toml config.toml`
- 401/403：检查 API Key、是否被环境变量覆盖
- 批处理无文件：确认目录下有 `.srt` 或 `.txt`
- 重试无效：确认 `failed_files` 可访问且路径正确
- 出现 `未命名` 类标题：确认本地是否运行了已更新代码，不应再看到硬编码兜底

## 3. 建议的排障顺序

1. 先确认命令和参数是否成功执行（`python -m pip install -e .` 已在当前虚拟环境）
2. 先跑 `--mock` 的最小链路
3. 对比 `batch_report.json` 中的失败列表与 `--retry-from` 流程
4. 查看 `structure_retry_count` / `structure_fallback_count` 是否异常升高

## 4. 结构化质量问题快速判断

- `content` 仍显著口语化：先看 `response_format` 是否已打开
- `--video-mark` 未生效：确认字幕中有有效时间戳
- 某文件持续回退：优先检查该文件切块后文本是否过短、是否存在大量噪声段
