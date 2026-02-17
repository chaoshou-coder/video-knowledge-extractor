# Video Knowledge Extractor

从讲座视频字幕提取结构化知识，生成教材。

[![CI](https://github.com/chaoshou-coder/video-knowledge-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/chaoshou-coder/video-knowledge-extractor/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[English Documentation](./README_EN.md)

---

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [详细使用指南](#详细使用指南)
- [技术架构](#技术架构)
- [API 参考](#api-参考)
- [配置说明](#配置说明)
- [开发指南](#开发指南)
- [故障排除](#故障排除)

---

## 功能特性

### 核心功能

| 功能 | 说明 | 技术实现 |
|------|------|----------|
| **字幕解析** | 支持 SRT 格式，自动处理时间戳和文本合并 | 正则表达式 + 状态机 |
| **智能清理** | 删除语气词、重复强调，保留核心内容 | 规则引擎 + LLM |
| **知识提取** | 自动识别知识点，生成结构化数据 | LLM + JSON 解析 |
| **聚类重组** | 跨文档主题聚类，构建课程结构 | 两阶段 LLM 聚类 |
| **去重融合** | 合并重复知识点，生成衔接段落 | 相似度计算 + LLM |
| **多格式导出** | Markdown / HTML / EPUB | 模板引擎 |
| **并行处理** | 多文档并行，提升效率 | asyncio + 线程池 |

### 支持的模型

- **Moonshot AI** (Kimi) - 推荐，国内可用
- **OpenRouter** - 支持 GPT-5.2-codex, Claude 等
- **Ollama** - 本地模型，无需联网

---

## 快速开始

### 安装

```bash
# 使用 pip
pip install video-knowledge-extractor

# 或使用 uv（更快）
uv pip install video-knowledge-extractor

# 开发安装（包含所有依赖）
pip install -e ".[full]"
```

### 配置 API Key

```bash
# 方法1: 环境变量
export KL_API_KEY="your-api-key"

# 方法2: 写入 .env 文件
echo "KL_API_KEY=your-api-key" > .env
```

### 处理第一个视频

```bash
# 处理单个字幕文件
kl process ./lecture.srt

# 输出目录: ./exports/
# 生成文件: lecture.md, lecture.html
```

---

## 详细使用指南

### CLI 命令

#### 1. 处理单个文件

```bash
kl process [选项] <文件路径>

选项:
  --output, -o    指定输出目录 (默认: ./exports/)
  --format, -f    输出格式: md, html, epub, all (默认: all)
  --model         指定模型 (覆盖环境变量)

示例:
  kl process ./math.srt -o ./output/ -f md
  kl process ./english.srt --model moonshot-v1-128k
```

#### 2. 批量处理

```bash
kl batch [选项] <目录路径>

选项:
  --workers, -w   并行工作数 (默认: 3)
  --pattern       文件匹配模式 (默认: *.srt)
  --output, -o    输出目录

示例:
  # 处理目录下所有 srt 文件
  kl batch ./course/ --workers 4

  # 处理特定模式
  kl batch ./videos/ --pattern "*.srt" -w 2
```

#### 3. Web UI

```bash
kl serve [选项]

选项:
  --host          绑定地址 (默认: 127.0.0.1)
  --port, -p      端口 (默认: 8080)

示例:
  kl serve --host 0.0.0.0 --port 3000
  # 访问 http://localhost:3000
```

#### 4. 导出格式

```bash
kl export [选项]

选项:
  --format, -f    格式: md, html, epub
  --input, -i     输入数据库 (默认: knowledge.db)
  --output, -o    输出文件

示例:
  kl export -f epub -o ./textbook.epub
```

#### 5. 查看状态

```bash
kl status
# 显示处理队列、已处理文档数、导出文件列表
```

### 配置多模型

```bash
# config.yaml
# 放在项目根目录或 ~/.config/kl/config.yaml

models:
  default: "moonshot-v1-8k"
  
  moonshot:
    api_key: "${KL_API_KEY}"
    base_url: "https://api.moonshot.cn/v1"
    model: "moonshot-v1-8k"
  
  openrouter:
    api_key: "${OPENROUTER_KEY}"
    base_url: "https://openrouter.ai/api/v1"
    model: "openai/gpt-5.2-codex"
  
  ollama:
    base_url: "http://localhost:11434"
    model: "qwen2.5"

# 使用特定模型
kl process ./file.srt --model openrouter
```

---

## 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Video Knowledge Extractor                 │
└─────────────────────────────────────────────────────────────────┘

Input Layer          Processing Layer              Output Layer
┌─────────┐         ┌──────────────────┐          ┌───────────┐
│ SRT File│────┐    │                  │          │           │
└─────────┘    │    │  Stage 1: Clean  │          │ Markdown  │
               ├───→│  (Rule-based)    │─────────→│           │
┌─────────┐    │    │                  │          ├───────────┤
│SRT File │────┤    ├──────────────────┤          │   HTML    │
└─────────┘    │    │  Stage 2: Reduce │─────────→│           │
               │    │  (LLM)           │          ├───────────┤
┌─────────┐    │    │                  │          │   EPUB    │
│SRT File │────┘    ├──────────────────┤─────────→│           │
└─────────┘         │  Stage 3: Extract│          └───────────┘
                    │  (LLM → JSON)    │
Batch Input         ├──────────────────┤
                    │  Stage 4: Cluster│
                    │  (Cross-doc)     │
                    ├──────────────────┤
                    │  Stage 5: Fusion │
                    │  (Deduplicate)   │
                    └──────────────────┘
```

### 数据处理流程

```
原始字幕 → 解析 → 清理 → 提炼 → 结构化 → 聚类 → 融合 → 导出

1. 解析 (SRT Parser)
   - 读取时间戳和文本
   - 合并短句
   - 输出: List[SubtitleEntry]

2. 清理 (Text Cleaner)
   - 删除语气词: "嗯", "啊", "那个"
   - 删除重复强调
   - 保留段落结构
   - 输出: Cleaned Text

3. 提炼 (Noise Reduction)
   - LLM 删除开场白、闲聊
   - 保留核心干货
   - 输出: Core Content

4. 结构化 (Knowledge Extraction)
   - LLM 提取知识点
   - 生成 JSON: {title, content, video_markers}
   - 输出: List[KnowledgePoint]

5. 聚类 (Cross-Document Clustering)
   - 阶段1: 主题识别 (LLM)
   - 阶段2: 结构构建 (LLM)
   - 输出: CourseStructure

6. 融合 (Knowledge Fusion)
   - 相似度计算
   - 合并重复知识点
   - 生成衔接段落
   - 输出: MergedKnowledge

7. 导出 (Export)
   - Markdown: 纯文本，易于编辑
   - HTML: 带样式，可直接阅读
   - EPUB: 电子书格式
```

### 模块说明

#### src/srt_parser.py
```python
class SRTParser:
    """SRT 字幕解析器"""
    
    def parse(file_path: Path) -> List[SubtitleEntry]:
        """解析 SRT 文件"""
        # 处理时间戳格式: 00:00:01,000 --> 00:00:05,000
        # 返回带时间信息的文本块
    
    def merge_short_entries(
        entries: List[SubtitleEntry],
        min_duration: float = 2.0
    ) -> List[SubtitleEntry]:
        """合并短句，提高连贯性"""
```

#### src/workflow.py
```python
class WorkflowEngine:
    """工作流引擎 - 4阶段顺序执行"""
    
    async def process_document(doc: Document) -> Document:
        """处理单个文档"""
        doc = await _stage_clean(doc)      # 清理
        doc = await _stage_reduce(doc)     # 提炼
        doc = await _stage_structure(doc)  # 结构化
        doc = await _stage_video_mark(doc) # 视频标记
        return doc
```

#### src/clustering.py
```python
class CrossDocumentClusteringSkill:
    """跨文档聚类"""
    
    async def cluster(points: List[KnowledgePoint]) -> CourseStructure:
        """两阶段聚类"""
        # 阶段1: LLM 识别主题
        topics = await _identify_topics(points)
        # 阶段2: LLM 构建课程结构
        structure = await _build_course_structure(topics)
        return structure
```

#### src/fusion.py
```python
class KnowledgeFusionSkill:
    """知识融合"""
    
    async def merge_duplicates(points: List[KnowledgePoint]) -> List[MergedKnowledge]:
        """去重融合"""
        # 1. 相似度计算
        # 2. 预筛选
        # 3. LLM 确认
        # 4. 合并
```

#### src/export.py
```python
class TextbookExporter:
    """教材导出器"""
    
    def export_markdown(course, chapters, transitions) -> str:
        """导出 Markdown"""
        
    def export_html(course, chapters, transitions) -> str:
        """导出 HTML"""
        
    def export_epub(course, chapters, transitions) -> str:
        """导出 EPUB"""
```

---

## API 参考

### Python API

```python
from src.workflow import WorkflowEngine, ProgressTracker, KnowledgePoint
from src.srt_parser import SRTParser
from src.llm_client import LLMClient

# 初始化
llm = LLMClient(api_key="your-key")
tracker = ProgressTracker(db_path="knowledge.db")
engine = WorkflowEngine(llm, tracker)

# 处理单个文档
from pathlib import Path
doc = await engine.process_document(Path("./lecture.srt"))

# 访问结果
print(f"知识点数量: {len(doc.knowledge_points)}")
for point in doc.knowledge_points:
    print(f"- {point.title}: {point.content[:100]}...")
```

### 数据模型

```python
@dataclass
class KnowledgePoint:
    title: str              # 知识点标题
    content: str            # 详细内容
    video_markers: List[Dict]  # 视频标记 [{time, description}]
    source_file: str        # 来源文件
    importance: int         # 重要程度 1-5

@dataclass
class CourseStructure:
    name: str               # 课程名称
    chapters: List[Dict]    # 章节列表
    topics: List[TopicCluster]  # 主题聚类
    prerequisites: Dict     # 前置知识关系
```

---

## 配置说明

### 环境变量

| 变量名 | 说明 | 必填 | 示例 |
|--------|------|------|------|
| `KL_API_KEY` | LLM API Key | 是 | `sk-...` |
| `KL_BASE_URL` | API 基础 URL | 否 | `https://api.moonshot.cn/v1` |
| `KL_MODEL` | 模型名称 | 否 | `moonshot-v1-8k` |

### 配置文件

```yaml
# ~/.config/kl/config.yaml

# 模型配置
models:
  default: moonshot
  
  moonshot:
    api_key: "${KL_API_KEY}"
    base_url: "https://api.moonshot.cn/v1"
    model: "moonshot-v1-8k"
    timeout: 60
  
  openrouter:
    api_key: "${OPENROUTER_KEY}"
    base_url: "https://openrouter.ai/api/v1"
    model: "openai/gpt-5.2-codex"

# 处理配置
processing:
  workers: 3              # 并行工作数
  batch_size: 10          # 批处理大小
  max_retries: 3          # 最大重试次数

# 导出配置
export:
  default_format: "md"
  output_dir: "./exports"
  include_video_refs: true
```

---

## 开发指南

### 本地开发

```bash
# 克隆仓库
git clone https://github.com/chaoshou-coder/video-knowledge-extractor.git
cd video-knowledge-extractor

# 安装依赖
pip install -e ".[full]"

# 运行测试
pytest tests/test_core.py -v
python tests/bdd_runner.py
```

### 添加新功能

1. **添加新的清理规则**
```python
# src/workflow.py
class TextCleaner:
    def clean(self, text: str) -> str:
        # 添加新规则
        text = self._remove_new_filler(text)
        return text
    
    def _remove_new_filler(self, text: str) -> str:
        # 实现新规则
        return re.sub(r'新的语气词', '', text)
```

2. **添加新的导出格式**
```python
# src/export.py
class TextbookExporter:
    def export_pdf(self, course, chapters) -> str:
        # 实现 PDF 导出
        pass
```

---

## 故障排除

### 常见问题

**Q: API 调用失败**
```
错误: Connection timeout
解决: 
  1. 检查网络连接
  2. 增加超时时间: KL_TIMEOUT=120
  3. 切换模型或 API 提供商
```

**Q: 解析失败**
```
错误: Invalid SRT format
解决:
  1. 检查字幕文件编码 (应为 UTF-8)
  2. 检查时间戳格式
  3. 尝试手动修复文件
```

**Q: 输出为空**
```
症状: 处理完成但没有知识点
原因:
  1. 字幕太短 (< 100 字符)
  2. 内容过于口语化
解决:
  1. 检查字幕质量
  2. 调整清理规则
  3. 使用更强的模型
```

### 调试模式

```bash
# 开启详细日志
export KL_DEBUG=1
kl process ./file.srt

# 查看数据库内容
sqlite3 knowledge.db "SELECT * FROM documents;"
```

---

## 许可

[MIT License](./LICENSE)

---

## 贡献

欢迎贡献！请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)

---

## 致谢

- OpenCode - 代码生成
- Moonshot AI / OpenRouter - LLM API
- 开源社区
