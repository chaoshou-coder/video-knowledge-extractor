# 使用说明（安装、配置、命令与排障）

本文档面向日常开发、测试与投产使用，提供从安装到故障排查的完整路径。

## 1. 环境要求

- Python `3.10+`
- 建议使用虚拟环境（Windows 可用 `python -m venv video-knowledge-extractor.venv`）
- 建议保证终端默认编码为 UTF-8（Windows 推荐 `chcp 65001`）

## 2. 安装

在项目根目录执行：

```bash
python -m pip install -e .
```

验证安装：

```bash
kl --help
python kl.py --help
```

可选依赖（按需）：

```bash
# 导出相关依赖（epub/html）
python -m pip install -e ".[export]"

# 向量检索相关依赖
python -m pip install -e ".[vector]"

# 全量依赖
python -m pip install -e ".[full]"
```

## 3. 配置模型

复制模板：

```bash
# Linux/macOS
cp config.example.toml config.toml

# Windows PowerShell
copy config.example.toml config.toml
```

最小配置示例：

```toml
[model]
api_base = "https://openrouter.ai/api/v1"
api_key = "sk-or-your-api-key"
model = "google/gemini-2.5-flash-lite"
timeout = 300

[processing]
chunk_size = 60000
```

环境变量：

- `KL_MODEL_API_KEY`：覆盖 `config.toml` 的 `model.api_key`
- `KL_APP_URL`：OpenRouter 请求头 `HTTP-Referer`（可选）
- `KL_APP_NAME`：OpenRouter 请求头 `X-Title`（可选）

## 4. 快速开始

### 4.1 单文件（mock，不调用外部 API）

```bash
python kl.py process examples/sample1.srt --mock -o exports
python kl.py process examples/sample2.txt --mock -o exports
```

### 4.2 批处理（mock）

```bash
python kl.py batch examples --mock --workers 2 -o exports
python kl.py batch examples --mock --build --format markdown -o exports
```

### 4.3 真实模型

```bash
python kl.py process examples/sample1.srt --config config.toml -o exports_prod
python kl.py batch examples --config config.toml --build --format markdown -o exports_prod
```

可选视频标记阶段：

```bash
python kl.py batch examples --config config.toml --build --format markdown -o exports_prod --video-mark
```

## 5. CLI 命令总览

### 5.1 `process` 处理单文件

```bash
kl process [OPTIONS] FILE_PATH
```

常用参数：

- `--config`：配置文件路径（默认 `config.toml`）
- `--mock`：模拟模式
- `--video-mark`：启用视频标记阶段
- `-o, --output`：输出目录（默认 `./exports`）

### 5.2 `batch` 批处理目录

```bash
kl batch [OPTIONS] DIRECTORY
```

常用参数：

- `-w, --workers`：并行 worker 数（默认 `3`）
- `-b, --build`：执行融合/聚类/导出全流程
- `-f, --format`：`markdown|epub|html|all`
- `-o, --output`：输出目录（默认 `./exports`）
- `--config` / `--mock` / `--video-mark`

### 5.3 `status` 查看处理状态

```bash
kl status
```

### 5.4 `parse` 仅解析字幕

```bash
kl parse examples/sample1.srt
kl parse examples/sample2.txt
```

### 5.5 Wizard 模式

```bash
python kl.py
```

无子命令时，进入交互式引导；适合人工临时使用。

## 6. 输出产物说明

`process` 模式输出：

- `<output>/<stem>_cleaned.md`
- `<output>/<stem>_structured.md`

`batch` 模式输出：

- `<output>/cleaned/`
- `<output>/structured/`

`batch --build` 额外输出：

- 教材文件（Markdown/HTML/EPUB）

## 7. 推荐工作流（生产最小闭环）

1. `pip install -e .` 安装项目
2. 先用 `--mock` 跑通 examples
3. 配置 `config.toml` 后切到真实模型
4. 小批量验证输出质量
5. 扩大批量并开启 `--build`

## 8. 常见问题与修复

- `ModuleNotFoundError: No module named 'click'`
  - 重新安装项目依赖：`python -m pip install -e .`
- `ModuleNotFoundError: No module named 'src'`
  - 通常是安装不完整或环境错位，执行：`python -m pip install -e .`
  - 确认当前终端使用的是目标虚拟环境。
- `未找到配置文件 config.toml`
  - 从 `config.example.toml` 复制并填写。
- `401/403`
  - 检查 `api_key`，以及是否被 `KL_MODEL_API_KEY` 覆盖。
- 批处理找不到文件
  - 确认目录下存在 `.srt` 或 `.txt` 文件。
