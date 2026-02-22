"""
Core workflow - 极简实现，无框架依赖
"""

import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Protocol

from .llm_provider import ProviderRegistry
from .srt_parser import SRTParser


class TextGenerator(Protocol):
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        system_prompt: str | None = None,
        extra_payload: Dict[str, Any] | None = None,
    ) -> str:
        ...


@dataclass
class KnowledgePoint:
    """知识点"""

    title: str
    content: str
    video_markers: List[Dict[str, str]] = field(default_factory=list)
    source_file: str = ""
    importance: int = 3  # 1-5


@dataclass
class Document:
    """文档对象"""

    path: Path
    content: str = ""
    course_name: Optional[str] = None
    knowledge_points: List[KnowledgePoint] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SemanticSegment:
    """语义分段"""

    title: str
    start_line: int
    end_line: int
    content: str


@dataclass
class TextChunk:
    """最终处理分块"""

    title: str
    content: str
    start_line: int
    end_line: int
    segment_index: int


class ProgressTracker:
    """SQLite 进度追踪 - 替代外部队列"""

    def __init__(self, db_path: str = "knowledge.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
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
                video_markers TEXT,
                source_file TEXT,
                FOREIGN KEY (doc_id) REFERENCES documents(id)
            );
            """
        )
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
        row = conn.execute("SELECT id FROM documents WHERE path = ?", (path,)).fetchone()
        conn.close()
        return row[0] if row else 0

    def update_status(
        self, doc_id: int, status: str, stage: Optional[str] = None, result: Optional[str] = None
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE documents SET status = ?, stage = ?, result = ? WHERE id = ?",
            (status, stage, result, doc_id),
        )
        conn.commit()
        conn.close()

    def save_knowledge_point(self, doc_id: int, point: KnowledgePoint) -> None:
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
    """Stage 1: 规则清理，无需 LLM。"""

    NOISE_PATTERNS = [
        (
            r"\b(um|uh|uhh|erm|like|you know|right|so|well|okay|ok|actually|basically|literally)\b[,.]?\s*",
            "",
        ),
        (r"(嗯+|啊+|哦+|哎+|唉+|哼+)[,，]?\s*", ""),
        (r"(对吧|那个|这个|就是|然后)[,，]?\s*", ""),
        (r"(大家可以看到|我们来看一下|好的|那么)[,，]?\s*", ""),
        (r"\n\s*\n\s*\n+", "\n\n"),
    ]

    def clean(self, text: str) -> str:
        original_length = len(text)
        for pattern, replacement in self.NOISE_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" +\n", "\n", text)
        text = re.sub(r"\n +", "\n", text)

        if len(text) < original_length * 0.3:
            text = re.sub(r"\s+", " ", text)
        return text.strip()


class MockLLMClient:
    """模拟 LLM 客户端 - 用于测试，不调用外部 API"""

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        system_prompt: str | None = None,
        extra_payload: Dict[str, Any] | None = None,
    ) -> str:
        await asyncio.sleep(0.02)
        prompt_lower = prompt.lower()

        if "语义分段任务" in prompt:
            total_lines_match = re.search(r"总行数:\s*(\d+)", prompt)
            total_lines = int(total_lines_match.group(1)) if total_lines_match else 1000
            mid = max(2, total_lines // 2)
            return json.dumps(
                {
                    "segments": [
                        {"title": "前半部分", "start_line": 1, "end_line": mid},
                        {
                            "title": "后半部分",
                            "start_line": mid + 1,
                            "end_line": total_lines,
                        },
                    ]
                },
                ensure_ascii=False,
            )
        if "子切分任务" in prompt:
            return json.dumps(
                {
                    "chunks": [
                        {
                            "title": "子块1",
                            "content": "这是子切后的内容块，保持原有语义顺序。",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        if "清洗任务" in prompt:
            return "这是清洗后的核心内容，保留事实和观点。"
        if "结构化提取任务" in prompt:
            return """{
  "points": [
    {"title": "示例知识点", "content": "示例内容，包含细节。"}
  ]
}"""
        if "识别可以合并的相似主题" in prompt:
            return """{
  "merged_topics": [
    {
      "id": "topic_0",
      "title": "核心概念",
      "description": "合并后的核心概念",
      "original_indices": [0],
      "keywords": ["概念", "基础"]
    }
  ]
}"""
        if "识别其中的主题聚类" in prompt or "主题聚类" in prompt:
            return """{
  "topics": [
    {
      "id": "topic_0",
      "title": "核心概念",
      "description": "基础定义和原理",
      "point_indices": [0],
      "keywords": ["定义", "原理"]
    }
  ]
}"""
        if "设计教材的章节结构" in prompt:
            return """{
  "course_name": "示例课程",
  "chapters": [
    {
      "order": 1,
      "title": "核心概念",
      "topic_ids": ["topic_0"],
      "description": "掌握核心概念",
      "learning_objectives": ["理解基本定义"]
    }
  ],
  "prerequisites": {
    "核心概念": []
  }
}"""
        if "判断它们是否重复或高度相似" in prompt:
            return """{
  "is_duplicate": false,
  "best_title": "示例标题",
  "confidence": 0.2,
  "reason": "mock: 默认不判重"
}"""
        if "整合以下" in prompt:
            return "这是合并后的知识点内容。"
        if "写一段衔接段落" in prompt:
            return "上一章建立了基础概念，本章将在此基础上推进到更完整的应用场景。"
        if "需看视频画面" in prompt or ("视频" in prompt and "画面" in prompt):
            return "[需看视频画面: 00:01-00:10]（图示说明）\n示例内容。"
        if "json" in prompt_lower:
            return """{
  "points": [
    {"title": "示例知识点", "content": "示例内容"}
  ]
}"""
        if "清理" in prompt or "删除" in prompt or "干货" in prompt:
            return "这是清理后的核心内容。"
        return "模拟生成的内容。"


class WorkflowEngine:
    """工作流引擎 - 语义分段 + 清洗 + 结构化"""

    def __init__(
        self,
        providers: ProviderRegistry | TextGenerator,
        tracker: ProgressTracker,
        enable_video_mark: bool = False,
        chunk_size: int = 60000,
        output_dir: str = "./exports",
        split_output_dirs: bool = False,
    ):
        if isinstance(providers, ProviderRegistry):
            self.providers = providers
            self.llm = providers.get()
            self.chunk_size = providers.chunk_size
        elif hasattr(providers, "generate"):
            self.providers = None
            self.llm = providers  # type: ignore[assignment]
            self.chunk_size = max(1000, int(chunk_size))
        else:
            raise TypeError("providers 必须是 ProviderRegistry 或具备 generate() 的对象")

        self.tracker = tracker
        self.cleaner = TextCleaner()
        self.enable_video_mark = enable_video_mark
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.split_output_dirs = split_output_dirs
        if self.split_output_dirs:
            self.cleaned_output_dir = self.output_dir / "cleaned"
            self.structured_output_dir = self.output_dir / "structured"
            self.cleaned_output_dir.mkdir(parents=True, exist_ok=True)
            self.structured_output_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.cleaned_output_dir = self.output_dir
            self.structured_output_dir = self.output_dir

    async def process_document(self, doc_path: Path) -> Document:
        """处理单个文档并输出清洗/结构化两份结果"""
        total_started = perf_counter()
        stage_durations: Dict[str, float] = {}
        doc_id = self.tracker.add_document(str(doc_path))
        doc = Document(path=doc_path, content=self._load_document_content(doc_path))
        processed_chars = len(doc.content)

        self.tracker.update_status(doc_id, "processing", "rule_cleaning")
        stage_started = perf_counter()
        doc.content = self.cleaner.clean(doc.content)
        stage_durations["rule_cleaning"] = perf_counter() - stage_started

        self.tracker.update_status(doc_id, "processing", "semantic_segmentation")
        stage_started = perf_counter()
        semantic_segments = await self._stage_semantic_segmentation(doc.content)
        stage_durations["semantic_segmentation"] = perf_counter() - stage_started

        self.tracker.update_status(doc_id, "processing", "sub_chunking")
        stage_started = perf_counter()
        chunks = await self._stage_sub_chunk(semantic_segments)
        stage_durations["sub_chunking"] = perf_counter() - stage_started

        self.tracker.update_status(doc_id, "processing", "noise_reduction")
        stage_started = perf_counter()
        cleaned_chunks = await self._stage_noise_reduction(chunks)
        stage_durations["noise_reduction"] = perf_counter() - stage_started
        doc.content = "\n\n".join(chunk.content for chunk in cleaned_chunks).strip()

        cleaned_output = self._save_cleaned_markdown(doc.path, semantic_segments, cleaned_chunks)

        self.tracker.update_status(doc_id, "processing", "structuring")
        stage_started = perf_counter()
        doc.knowledge_points = await self._stage_structure(cleaned_chunks, doc.path)
        stage_durations["structuring"] = perf_counter() - stage_started
        structured_output = self._save_structured_markdown(
            doc.path, doc.knowledge_points, cleaned_chunks
        )

        if self.enable_video_mark:
            self.tracker.update_status(doc_id, "processing", "video_marking")
            stage_started = perf_counter()
            doc = await self._stage_video_mark(doc)
            stage_durations["video_marking"] = perf_counter() - stage_started
        else:
            self.tracker.update_status(doc_id, "processing", "video_marking_skipped")
            stage_durations["video_marking"] = 0.0

        doc.metadata["chunk_size"] = self.chunk_size
        doc.metadata["semantic_segments"] = [
            {
                "title": segment.title,
                "start_line": segment.start_line,
                "end_line": segment.end_line,
            }
            for segment in semantic_segments
        ]
        doc.metadata["chunk_count"] = len(cleaned_chunks)
        doc.metadata["cleaned_output"] = str(cleaned_output)
        doc.metadata["structured_output"] = str(structured_output)
        doc.metadata["processed_chars"] = processed_chars
        doc.metadata["extracted_chars"] = sum(len(point.content) for point in doc.knowledge_points)
        doc.metadata["stage_durations"] = stage_durations
        doc.metadata["total_duration"] = perf_counter() - total_started

        self.tracker.update_status(doc_id, "done", "completed")
        for point in doc.knowledge_points:
            self.tracker.save_knowledge_point(doc_id, point)

        return doc

    def _load_document_content(self, doc_path: Path) -> str:
        text = doc_path.read_text(encoding="utf-8")
        if doc_path.suffix.lower() not in {".srt", ".txt"}:
            return text

        entries = SRTParser.parse(text)
        if not entries:
            return text
        return SRTParser.to_plaintext(entries, include_timestamp=False)

    def _estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text) / 3))

    async def _stage_semantic_segmentation(self, text: str) -> List[SemanticSegment]:
        lines = text.splitlines()
        if not lines:
            return [SemanticSegment(title="全文", start_line=1, end_line=1, content=text)]

        numbered_text = "\n".join(f"{idx + 1}|{line}" for idx, line in enumerate(lines))
        prompt = f"""语义分段任务：
请你通读全文，根据主题连续性划分段落。

要求：
1) 输出 JSON，不要输出正文；
2) 每段必须包含 title、start_line、end_line；
3) start_line/end_line 使用下方行号（1 开始）；
4) 段落按出现顺序排列，尽量覆盖全文。

总行数: {len(lines)}

文本（带行号）：
{numbered_text}

输出格式：
{{
  "segments": [
    {{"title": "段落标题", "start_line": 1, "end_line": 120}}
  ]
}}
"""
        try:
            result = await self.llm.generate(prompt, temperature=0.1)
            data = self._parse_json_response(result)
            raw_segments = data.get("segments", [])
            normalized = self._normalize_segments(raw_segments, len(lines))
            if not normalized:
                return [
                    SemanticSegment(
                        title="全文",
                        start_line=1,
                        end_line=len(lines),
                        content="\n".join(lines),
                    )
                ]

            segments: List[SemanticSegment] = []
            for item in normalized:
                start_line = item["start_line"]
                end_line = item["end_line"]
                content = "\n".join(lines[start_line - 1 : end_line]).strip()
                if not content:
                    continue
                segments.append(
                    SemanticSegment(
                        title=item["title"],
                        start_line=start_line,
                        end_line=end_line,
                        content=content,
                    )
                )
            if segments:
                return segments
        except Exception as exc:
            print(f"语义分段失败，回退为单段: {exc}")

        return [
            SemanticSegment(
                title="全文",
                start_line=1,
                end_line=len(lines),
                content="\n".join(lines),
            )
        ]

    def _normalize_segments(
        self, raw_segments: Any, total_lines: int
    ) -> List[Dict[str, int | str]]:
        if not isinstance(raw_segments, list):
            return []

        parsed: List[Dict[str, int | str]] = []
        for idx, item in enumerate(raw_segments):
            if not isinstance(item, dict):
                continue
            try:
                start = int(item.get("start_line", 0))
                end = int(item.get("end_line", 0))
            except (TypeError, ValueError):
                continue
            if end < start or start <= 0:
                continue
            start = max(1, min(start, total_lines))
            end = max(1, min(end, total_lines))
            if end < start:
                continue
            title = str(item.get("title", f"段落{idx + 1}")).strip() or f"段落{idx + 1}"
            parsed.append({"title": title, "start_line": start, "end_line": end})

        if not parsed:
            return []

        parsed.sort(key=lambda x: int(x["start_line"]))
        normalized: List[Dict[str, int | str]] = []
        cursor = 1
        for item in parsed:
            start = max(cursor, int(item["start_line"]))
            if start > total_lines:
                break
            end = max(start, int(item["end_line"]))
            end = min(end, total_lines)
            normalized.append(
                {"title": str(item["title"]), "start_line": start, "end_line": end}
            )
            cursor = end + 1
            if cursor > total_lines:
                break

        if cursor <= total_lines:
            normalized.append(
                {"title": "尾部补全", "start_line": cursor, "end_line": total_lines}
            )
        return normalized

    async def _stage_sub_chunk(self, segments: List[SemanticSegment]) -> List[TextChunk]:
        chunks: List[TextChunk] = []
        for segment_idx, segment in enumerate(segments):
            token_count = self._estimate_tokens(segment.content)
            if token_count <= self.chunk_size:
                chunks.append(
                    TextChunk(
                        title=segment.title,
                        content=segment.content,
                        start_line=segment.start_line,
                        end_line=segment.end_line,
                        segment_index=segment_idx,
                    )
                )
                continue

            subchunks = await self._llm_sub_chunk_segment(segment)
            if not subchunks:
                subchunks = self._fallback_sub_chunk(segment)
            chunks.extend(subchunks)
        return chunks

    async def _llm_sub_chunk_segment(self, segment: SemanticSegment) -> List[TextChunk]:
        prompt = f"""子切分任务：
以下是一个语义连续的大段内容，请按内容边界再切分为多个子块。

约束：
1) 每个子块建议不超过 {self.chunk_size} token；
2) 必须保持原始顺序，不能改写事实；
3) 必须输出每个子块的具体内容；
4) 只输出 JSON。

输出格式：
{{
  "chunks": [
    {{"title": "子块标题", "content": "子块正文"}}
  ]
}}

原段标题：{segment.title}
原段行号：{segment.start_line}-{segment.end_line}

原段内容：
{segment.content}
"""
        try:
            result = await self.llm.generate(prompt, temperature=0.1)
            data = self._parse_json_response(result)
            raw_chunks = data.get("chunks", [])
            if not isinstance(raw_chunks, list):
                return []

            normalized: List[TextChunk] = []
            for idx, item in enumerate(raw_chunks):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", f"{segment.title}-子块{idx + 1}")).strip()
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                if self._estimate_tokens(content) > int(self.chunk_size * 1.2):
                    for fallback_idx, piece in enumerate(
                        self._split_text_by_char_limit(content, self.chunk_size * 3)
                    ):
                        normalized.append(
                            TextChunk(
                                title=f"{title}-fallback-{fallback_idx + 1}",
                                content=piece,
                                start_line=segment.start_line,
                                end_line=segment.end_line,
                                segment_index=0,
                            )
                        )
                    continue
                normalized.append(
                    TextChunk(
                        title=title,
                        content=content,
                        start_line=segment.start_line,
                        end_line=segment.end_line,
                        segment_index=0,
                    )
                )
            return normalized
        except Exception as exc:
            print(f"子切分失败，回退规则切分: {exc}")
            return []

    def _fallback_sub_chunk(self, segment: SemanticSegment) -> List[TextChunk]:
        pieces = self._split_text_by_char_limit(segment.content, self.chunk_size * 3)
        return [
            TextChunk(
                title=f"{segment.title}-子块{idx + 1}",
                content=piece,
                start_line=segment.start_line,
                end_line=segment.end_line,
                segment_index=0,
            )
            for idx, piece in enumerate(pieces)
            if piece.strip()
        ]

    def _split_text_by_char_limit(self, text: str, limit: int) -> List[str]:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return [text]
        chunks: List[str] = []
        current = ""
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(line) <= limit:
                current = line
                continue
            # 单行超限，硬切
            for idx in range(0, len(line), limit):
                piece = line[idx : idx + limit]
                if len(piece) == limit:
                    chunks.append(piece)
                else:
                    current = piece
        if current:
            chunks.append(current)
        return chunks

    async def _stage_noise_reduction(self, chunks: List[TextChunk]) -> List[TextChunk]:
        if not chunks:
            return []

        semaphore = asyncio.Semaphore(4)
        progress_lock = asyncio.Lock()
        total = len(chunks)
        progress = {"done": 0}

        async def _tick() -> None:
            async with progress_lock:
                progress["done"] += 1
                done = progress["done"]
                msg = f"清洗 {done}/{total} 块..."
                if done < total:
                    print(f"\r{msg}", end="", flush=True)
                else:
                    print(f"\r{msg}")

        async def _clean_chunk(index: int, chunk: TextChunk) -> TextChunk:
            prompt = f"""清洗任务：
请清洗以下文本片段，删除口水话但保留信息细节。

要求：
1) 仅删除语气词、寒暄、重复强调和无信息量过渡句；
2) 保留所有事实、观点、术语、方法、数据、论据；
3) 不要摘要，不要改写逻辑顺序；

片段：
{chunk.content}
"""
            try:
                async with semaphore:
                    cleaned = await self.llm.generate(prompt, temperature=0.1)
                cleaned = cleaned.strip()
                if not cleaned or len(cleaned) < int(len(chunk.content) * 0.35):
                    cleaned = chunk.content
                return TextChunk(
                    title=chunk.title,
                    content=cleaned,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    segment_index=chunk.segment_index,
                )
            except Exception as exc:
                print(f"\n清洗分块失败 ({index + 1}/{total}): {exc}")
                return chunk
            finally:
                await _tick()

        return await asyncio.gather(
            *[_clean_chunk(index, chunk) for index, chunk in enumerate(chunks)]
        )

    async def _stage_structure(
        self, cleaned_chunks: List[TextChunk], source_path: Path
    ) -> List[KnowledgePoint]:
        if not cleaned_chunks:
            return [KnowledgePoint(title="内容摘要", content="", source_file=str(source_path))]

        semaphore = asyncio.Semaphore(4)
        progress_lock = asyncio.Lock()
        total = len(cleaned_chunks)
        progress = {"done": 0}

        async def _tick() -> None:
            async with progress_lock:
                progress["done"] += 1
                done = progress["done"]
                msg = f"结构化 {done}/{total} 块..."
                if done < total:
                    print(f"\r{msg}", end="", flush=True)
                else:
                    print(f"\r{msg}")

        async def _extract_chunk(index: int, chunk: TextChunk) -> List[KnowledgePoint]:
            prompt = f"""结构化提取任务：
从下述清洗后的讲座片段中提取尽可能完整的知识点，不要遗漏细节。

提取维度：
- 概念定义
- 方法步骤
- 事实信息
- 数据与结论
- 实践经验

要求：
1) 输出 JSON，字段必须是 points；
2) 每条 point 至少包含 title/content；
3) content 要保留细节，不要只写一句概括。

few-shot 示例：
{{
  "points": [
    {{
      "title": "强化学习在后训练中的作用",
      "content": "后训练阶段使用强化学习对模型行为进行目标对齐，关键环节包括奖励建模、策略迭代与评估闭环。该片段还强调了基础设施稳定性对实验吞吐量的影响。"
    }}
  ]
}}

当前片段：
{chunk.content}
"""
            try:
                async with semaphore:
                    result = await self.llm.generate(prompt, temperature=0.2)
                data = self._parse_json_response(result)
                raw_points = (
                    data.get("points")
                    or data.get("knowledge_points")
                    or data.get("items")
                    or []
                )
                parsed: List[KnowledgePoint] = []
                for item in raw_points:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title", "")).strip() or "未命名知识点"
                    content = str(item.get("content", "")).strip()
                    if not content:
                        continue
                    parsed.append(
                        KnowledgePoint(
                            title=title,
                            content=content,
                            source_file=str(source_path),
                        )
                    )
                return parsed
            except Exception as exc:
                print(f"\n结构化分块失败 ({index + 1}/{total}): {exc}")
                return []
            finally:
                await _tick()

        chunk_results = await asyncio.gather(
            *[_extract_chunk(i, chunk) for i, chunk in enumerate(cleaned_chunks)]
        )
        merged_points: List[KnowledgePoint] = []
        seen = set()
        for points in chunk_results:
            for point in points:
                key = f"{point.title}::{point.content}"
                if key in seen:
                    continue
                seen.add(key)
                merged_points.append(point)

        if not merged_points:
            merged_points = [
                KnowledgePoint(
                    title="内容摘要",
                    content="\n\n".join(chunk.content for chunk in cleaned_chunks)[:1000],
                    source_file=str(source_path),
                )
            ]
        return merged_points

    def _save_cleaned_markdown(
        self,
        source_path: Path,
        semantic_segments: List[SemanticSegment],
        cleaned_chunks: List[TextChunk],
    ) -> Path:
        out_path = self.cleaned_output_dir / f"{source_path.stem}_cleaned.md"
        lines: List[str] = [f"# {source_path.stem} 清洗结果", ""]
        lines.extend(
            [
                "## 分块策略",
                "",
                f"- chunk_size(token): {self.chunk_size}",
                f"- 语义分段数: {len(semantic_segments)}",
                f"- 最终处理分块数: {len(cleaned_chunks)}",
                "- 语义分段起始点:",
            ]
        )
        for idx, segment in enumerate(semantic_segments, 1):
            lines.append(
                f"  - S{idx}: line {segment.start_line} ({segment.title}) -> line {segment.end_line}"
            )
        lines.extend(["", "---", ""])

        for idx, chunk in enumerate(cleaned_chunks, 1):
            lines.extend(
                [
                    f"## Chunk {idx}: {chunk.title}",
                    f"_source_lines: {chunk.start_line}-{chunk.end_line}_",
                    "",
                    chunk.content.strip(),
                    "",
                ]
            )

        out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return out_path

    def _save_structured_markdown(
        self,
        source_path: Path,
        points: List[KnowledgePoint],
        cleaned_chunks: List[TextChunk],
    ) -> Path:
        out_path = self.structured_output_dir / f"{source_path.stem}_structured.md"
        lines: List[str] = [f"# {source_path.stem} 结构化结果", ""]
        lines.extend(
            [
                "## 统计",
                "",
                f"- 分块数: {len(cleaned_chunks)}",
                f"- 知识点数: {len(points)}",
                "",
                "---",
                "",
            ]
        )

        for idx, point in enumerate(points, 1):
            lines.extend([f"## {idx}. {point.title}", "", point.content.strip(), ""])

        out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return out_path

    async def _stage_video_mark(self, doc: Document) -> Document:
        for point in doc.knowledge_points:
            prompt = f"""分析以下知识点内容，判断是否需要配合视频画面才能理解：

知识点：{point.title}
内容：{point.content}

如果需要视频画面（如图表、公式推导、动画），在相关段落前插入标记：
[需看视频画面: 时间范围]（图示说明）

输出修改后的内容（如无视频需求则输出原文）："""

            try:
                marked_content = await self.llm.generate(
                    prompt, temperature=0.2
                )
                point.content = marked_content
                point.video_markers = self._extract_video_markers(marked_content)
            except Exception as exc:
                print(f"视频标记失败: {exc}")
        return doc

    def _extract_video_markers(self, text: str) -> List[Dict[str, str]]:
        matches = re.findall(
            r"\[需看视频画面:\s*([^\]]+)\]\s*(?:[（(]([^）)]+)[）)])?",
            text,
        )
        markers: List[Dict[str, str]] = []
        for time_range, description in matches:
            markers.append(
                {
                    "time": str(time_range).strip(),
                    "description": str(description).strip() if description else "",
                }
            )
        return markers

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        patterns = [
            r"```json\s*\n(.*?)\n```",
            r"```\s*\n(.*?)\n```",
            r"(\{[\s\S]*\})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {}


class BatchProcessor:
    """批量处理器 - asyncio 并行"""

    def __init__(self, engine: WorkflowEngine, max_workers: int = 3):
        self.engine = engine
        self.semaphore = asyncio.Semaphore(max_workers)

    async def process_directory(self, dir_path: Path) -> List[Document]:
        files = sorted(list(dir_path.glob("*.srt")) + list(dir_path.glob("*.txt")))
        if not files:
            return []

        async def _process_one(file_path: Path) -> Document:
            async with self.semaphore:
                return await self.engine.process_document(file_path)

        tasks = [_process_one(file_path) for file_path in files]
        return await asyncio.gather(*tasks)
