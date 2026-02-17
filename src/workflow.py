"""
Core workflow - 极简实现，无框架依赖
"""

import asyncio
import re
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
import sqlite3


@dataclass
class Document:
    """文档对象"""

    path: Path
    content: str = ""
    course_name: Optional[str] = None
    knowledge_points: List[Dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgePoint:
    """知识点"""

    title: str
    content: str
    video_markers: List[Dict] = field(default_factory=list)
    source_file: str = ""
    importance: int = 3  # 1-5


class ProgressTracker:
    """SQLite 进度追踪 - 替代外部队列"""

    def __init__(self, db_path: str = "knowledge.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                status TEXT DEFAULT 'pending',
                stage TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS knowledge_points (
                id INTEGER PRIMARY KEY,
                doc_id INTEGER,
                title TEXT,
                content TEXT,
                video_markers TEXT,  -- JSON
                source_file TEXT,
                FOREIGN KEY (doc_id) REFERENCES documents(id)
            );
        """)
        conn.commit()
        conn.close()

    def add_document(self, path: str) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "INSERT OR IGNORE INTO documents (path, status) VALUES (?, 'pending')",
            (path,),
        )
        conn.commit()
        doc_id = cursor.lastrowid or self._get_doc_id(path)
        conn.close()
        return doc_id

    def _get_doc_id(self, path: str) -> int:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT id FROM documents WHERE path = ?", (path,)
        ).fetchone()
        conn.close()
        return row[0] if row else 0

    def update_status(
        self, doc_id: int, status: str, stage: str = None, result: str = None
    ):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE documents SET status = ?, stage = ?, result = ? WHERE id = ?",
            (status, stage, result, doc_id),
        )
        conn.commit()
        conn.close()

    def save_knowledge_point(self, doc_id: int, point: KnowledgePoint):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO knowledge_points (doc_id, title, content, video_markers, source_file)
               VALUES (?, ?, ?, ?, ?)""",
            (
                doc_id,
                point.title,
                point.content,
                json.dumps(point.video_markers, ensure_ascii=False),
                point.source_file,
            ),
        )
        conn.commit()
        conn.close()


class TextCleaner:
    """Stage 1: 清理文本 - 规则即可，无需 LLM"""

    # 语气词和噪音模式
    NOISE_PATTERNS = [
        (
            r"\b(um|uh|uhh|erm|like|you know|right|so|well|okay|ok|actually|basically|literally)\b[,.]?\s*",
            "",
        ),  # 英文语气词
        (r"\s*[嗯啊哦嗯哼唉哎]?[,，]?\s*", ""),  # 中文语气词
        (r"\s*(对吧|那个|这个|就是|然后)[,，]?\s*", ""),  # 口头禅
        (r"\s*(大家可以看到|我们来看一下|好的|那么)[,，]?\s*", ""),  # 开场白
        (r"\n\s*\n\s*\n+", "\n\n"),  # 过多空行
    ]

    def clean(self, text: str) -> str:
        """清理文本 - 保留核心内容，仅去除语气词"""
        # 先保存原始内容长度用于验证
        original_length = len(text)

        for pattern, replacement in self.NOISE_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # 清理多余空格，但保留换行结构
        text = re.sub(r"[ \t]+", " ", text)  # 多个空格/制表符 -> 单个空格
        text = re.sub(r" +\n", "\n", text)  # 行尾空格 -> 无
        text = re.sub(r"\n +", "\n", text)  # 行首空格 -> 无

        # 验证：如果内容被删除了超过50%，可能是过度清理
        if len(text) < original_length * 0.3:
            # 返回原始内容，仅做基本清理
            text = re.sub(r"\s+", " ", text)

        return text.strip()


class LLMClient:
    """简单的 LLM 客户端 - 直接 httpx，无 LangChain"""

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key
        self.base_url = base_url or "https://api.moonshot.cn/v1"
        self.model = model or "moonshot-v1-8k"


class MockLLMClient:
    """模拟 LLM 客户端 - 用于测试，不调用 API"""

    def __init__(self):
        self.api_key = "mock"
        self.base_url = "mock"
        self.model = "mock"

    async def generate(self, prompt: str, temperature: float = 0.3) -> str:
        """返回模拟响应"""
        import asyncio

        await asyncio.sleep(0.1)  # 模拟延迟

        # 根据 prompt 内容返回不同模拟结果 (优先级：结构化 > 视频 > 清理 > 聚类)
        if "章节" in prompt or "chapters" in prompt.lower():
            # 聚类 - 构建课程结构
            return """{
  "course_name": "微积分基础",
  "chapters": [
    {"order": 1, "title": "导数概念", "topics": ["topic_0"]},
    {"order": 2, "title": "极限理论", "topics": ["topic_1"]}
  ],
  "prerequisites": {"导数概念": [], "极限理论": ["导数概念"]}
}"""
        elif "主题" in prompt and "合并" in prompt:
            # 聚类 - 主题合并
            return '{"merged_topics": [{"id": "topic_0", "title": "导数", "description": "导数相关内容", "original_indices": [0], "keywords": ["导数", "斜率"]}, {"id": "topic_1", "title": "极限", "description": "极限相关内容", "original_indices": [1], "keywords": ["极限", "趋势"]}]}'
        elif "主题聚类" in prompt or "topics" in prompt.lower():
            # 聚类 - 识别主题
            return '{"topics": [{"id": "topic_0", "title": "导数", "description": "导数的定义和几何意义", "point_indices": [0, 1], "keywords": ["导数", "斜率", "切线"]}, {"id": "topic_1", "title": "极限", "description": "极限的概念和意义", "point_indices": [2], "keywords": ["极限", "趋势"]}]}'
        elif "JSON" in prompt or "json" in prompt:
            # 结构化提取请求
            return '{"points": [{"title": "示例知识点", "content": "示例内容"}]}'
        elif "视频" in prompt and "画面" in prompt:
            # 视频标记请求
            return "[需看视频画面: 00:01-00:10]（图示说明）\n示例内容。"
        elif "清理" in prompt or "删除" in prompt or "干货" in prompt:
            # 返回简化后的文本
            return "这是清理后的核心内容。"
        else:
            return "模拟生成的内容。"


class WorkflowEngine:
    """工作流引擎 - 顺序执行 4 阶段"""

    def __init__(self, llm_client: LLMClient, tracker: ProgressTracker):
        self.llm = llm_client
        self.tracker = tracker
        self.cleaner = TextCleaner()

    async def process_document(self, doc_path: Path) -> Document:
        """处理单个文档"""
        # 添加到追踪
        doc_id = self.tracker.add_document(str(doc_path))

        # 读取文件
        doc = Document(path=doc_path, content=doc_path.read_text(encoding="utf-8"))

        # Stage 1: 清理
        self.tracker.update_status(doc_id, "processing", "cleaning")
        doc.content = self.cleaner.clean(doc.content)

        # Stage 2: 提炼干货 (LLM)
        self.tracker.update_status(doc_id, "processing", "noise_reduction")
        doc = await self._stage_noise_reduction(doc)

        # Stage 3: 结构化 (LLM)
        self.tracker.update_status(doc_id, "processing", "structuring")
        doc = await self._stage_structure(doc)

        # Stage 4: 标记视频 (LLM)
        self.tracker.update_status(doc_id, "processing", "video_marking")
        doc = await self._stage_video_mark(doc)

        # 保存结果
        self.tracker.update_status(doc_id, "done", "completed")
        for point in doc.knowledge_points:
            self.tracker.save_knowledge_point(doc_id, point)

        return doc

    async def _stage_noise_reduction(self, doc: Document) -> Document:
        """提炼干货"""
        prompt = f"""删除以下讲座文本中的开场白、闲聊、重复强调等口水话，保留核心知识点：

{doc.content[:4000]}

只输出清理后的干货内容，不要解释："""

        doc.content = await self.llm.generate(prompt)
        return doc

    async def _stage_structure(self, doc: Document) -> Document:
        """提取结构化知识"""
        prompt = f"""分析以下讲座内容，提取结构化知识点。

内容：
{doc.content[:3000]}

按以下 JSON 格式输出：
{{
  "points": [
    {{
      "title": "知识点标题",
      "content": "详细内容"
    }}
  ]
}}

只输出 JSON，不要其他内容："""

        try:
            result = await self.llm.generate(prompt)
            # 提取 JSON
            json_match = re.search(r"\{.*\}", result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                doc.knowledge_points = [
                    KnowledgePoint(
                        title=p["title"],
                        content=p["content"],
                        source_file=str(doc.path),
                    )
                    for p in data.get("points", [])
                ]
        except Exception as e:
            print(f"结构化失败: {e}")
            # 降级：单一点
            doc.knowledge_points = [
                KnowledgePoint(
                    title="内容", content=doc.content[:1000], source_file=str(doc.path)
                )
            ]

        return doc

    async def _stage_video_mark(self, doc: Document) -> Document:
        """标记需看视频处"""
        for point in doc.knowledge_points:
            prompt = f"""分析以下知识点内容，判断是否需要配合视频画面才能理解：

知识点：{point.title}
内容：{point.content}

如果需要视频画面（如图表、公式推导、动画），在相关段落前插入标记：
[需看视频画面: 时间范围]

例如：
[需看视频画面: 05:30-05:45] （图示：曲线切线示意）

输出修改后的内容（如无视频需求则输出原文）："""

            try:
                marked_content = await self.llm.generate(prompt)
                point.content = marked_content

                # 解析视频标记
                markers = re.findall(
                    r"\[需看视频画面:\s*([\d:]+-[\d:]+)\]\s*\(([^)]+)\)", marked_content
                )
                point.video_markers = [
                    {"time": m[0], "description": m[1]} for m in markers
                ]
            except Exception as e:
                print(f"视频标记失败: {e}")

        return doc


class BatchProcessor:
    """批量处理器 - asyncio 并行"""

    def __init__(self, engine: WorkflowEngine, max_workers: int = 3):
        self.engine = engine
        self.semaphore = asyncio.Semaphore(max_workers)

    async def process_directory(self, dir_path: Path) -> List[Document]:
        """处理目录下所有文档"""
        # 发现文件
        files = list(dir_path.glob("*.srt")) + list(dir_path.glob("*.txt"))

        async def _process_one(file_path: Path):
            async with self.semaphore:
                return await self.engine.process_document(file_path)

        # 并行处理
        tasks = [_process_one(f) for f in files]
        return await asyncio.gather(*tasks)
