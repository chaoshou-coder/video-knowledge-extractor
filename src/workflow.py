"""
Core workflow - 极简实现，无框架依赖
"""

import asyncio
import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Mapping, Optional, Protocol

from .llm_provider import ProviderRegistry
from .srt_parser import SRTParser, SubtitleEntry

_PRINT_LOCK = threading.Lock()


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
    time_ranges: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
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
    source_entries: List[SubtitleEntry] = field(default_factory=list)


@dataclass
class TextChunk:
    """最终处理分块"""

    title: str
    content: str
    start_line: int
    end_line: int
    segment_index: int
    start_time: str = ""
    end_time: str = ""
    has_timestamp: bool = False
    time_spans: List[Dict[str, str]] = field(default_factory=list)


class DocumentProcessingError(RuntimeError):
    """单文件处理失败（携带阶段信息）"""

    def __init__(self, file_path: Path, stage: str, detail: str):
        self.file_path = str(file_path)
        self.stage = stage
        self.detail = detail
        super().__init__(f"[{stage}] {file_path.name}: {detail}")


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

    @staticmethod
    def _stage_label(stage: str) -> str:
        stage_map = {
            "rule_cleaning": "规则清理",
            "semantic_segmentation": "语义分段",
            "content_chunking": "内容分块",
            "sub_chunking": "子切分",
            "structuring": "结构化",
            "video_marking": "视频标记",
            "video_marking_skipped": "视频标记",
            "unknown": "未知阶段",
        }
        return stage_map.get(stage, stage)

    def _log(self, doc_path: Path, message: str) -> None:
        with _PRINT_LOCK:
            print(f"[{doc_path.name}] {message}")

    def _stage_done(self, doc_path: Path, stage: str, elapsed: float) -> None:
        label = self._stage_label(stage)
        self._log(doc_path, f"{label}已完成 ({elapsed:.2f}s)")

    def _mark_failed(
        self, doc_id: int, doc_path: Path, stage: str, exc: Exception | str
    ) -> None:
        detail = str(exc)
        label = self._stage_label(stage)
        self._log(doc_path, f"{label}失败: {detail}")
        self.tracker.update_status(doc_id, "failed", stage, detail)
        raise DocumentProcessingError(doc_path, stage, detail)

    async def process_document(self, doc_path: Path) -> Document:
        """处理单个文档并输出清洗/结构化两份结果"""
        total_started = perf_counter()
        stage_durations: Dict[str, float] = {}
        doc_id = self.tracker.add_document(str(doc_path))
        raw_content, subtitle_entries = self._load_document_source(doc_path)
        doc = Document(path=doc_path, content=raw_content)
        has_timestamps = bool(subtitle_entries)
        processed_chars = len(doc.content)

        try:
            self.tracker.update_status(doc_id, "processing", "rule_cleaning")
            stage_started = perf_counter()
            doc.content = self.cleaner.clean(doc.content)
            stage_durations["rule_cleaning"] = perf_counter() - stage_started
            self._stage_done(doc_path, "rule_cleaning", stage_durations["rule_cleaning"])

            self.tracker.update_status(doc_id, "processing", "sub_chunking")
            stage_started = perf_counter()
            try:
                semantic_segments = await self._stage_semantic_segmentation(
                    doc.content, subtitle_entries
                )
                cleaned_chunks = await self._stage_sub_chunk(
                    semantic_segments, source_hint=doc.path
                )
            except Exception as exc:
                self._mark_failed(doc_id, doc_path, "sub_chunking", exc)
            stage_durations["sub_chunking"] = perf_counter() - stage_started
            self._stage_done(
                doc_path,
                "sub_chunking",
                stage_durations["sub_chunking"],
            )

            cleaned_output = self._save_cleaned_markdown(
                doc.path, semantic_segments, cleaned_chunks
            )

            self.tracker.update_status(doc_id, "processing", "structuring")
            stage_started = perf_counter()
            structure_metrics: Dict[str, int] = {}
            try:
                doc.knowledge_points = await self._stage_structure_single_pass(
                    cleaned_chunks=cleaned_chunks,
                    source_path=doc.path,
                    has_timestamps=has_timestamps,
                    structure_metrics=structure_metrics,
                )
            except Exception as exc:
                self._mark_failed(doc_id, doc_path, "structuring", exc)
            stage_durations["structuring"] = perf_counter() - stage_started
            structured_output = self._save_structured_markdown(
                doc.path, doc.knowledge_points, cleaned_chunks
            )
            self._stage_done(doc_path, "structuring", stage_durations["structuring"])

            if self.enable_video_mark:
                self.tracker.update_status(doc_id, "processing", "video_marking")
                stage_started = perf_counter()
                try:
                    doc = await self._stage_video_mark(doc, doc.path)
                except Exception as exc:
                    self._mark_failed(doc_id, doc_path, "video_marking", exc)
                stage_durations["video_marking"] = perf_counter() - stage_started
                self._stage_done(doc_path, "video_marking", stage_durations["video_marking"])
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
            doc.metadata["extracted_chars"] = sum(
                len(str(point.content)) for point in doc.knowledge_points
            )
            doc.metadata["has_timestamps"] = has_timestamps
            doc.metadata["estimated_time_range_count"] = self._count_estimated_time_ranges(
                doc.knowledge_points
            )
            doc.metadata["structure_retry_count"] = structure_metrics.get("retry_count", 0)
            doc.metadata["structure_fallback_count"] = structure_metrics.get(
                "fallback_count", 0
            )
            doc.metadata["structure_weak_chunk_count"] = structure_metrics.get(
                "weak_chunk_count", 0
            )
            doc.metadata["stage_durations"] = stage_durations
            doc.metadata["total_duration"] = perf_counter() - total_started

            self.tracker.update_status(doc_id, "done", "completed")
            for point in doc.knowledge_points:
                point.content = str(point.content)
                point.title = self._sanitize_structure_title(point.title)
                self.tracker.save_knowledge_point(doc_id, point)
            return doc
        except DocumentProcessingError:
            raise
        except Exception as exc:
            self._mark_failed(doc_id, doc_path, "unknown", exc)

    def _load_document_content(self, doc_path: Path) -> str:
        raw_content, _ = self._load_document_source(doc_path)
        return raw_content

    def _load_document_source(self, doc_path: Path) -> tuple[str, List[SubtitleEntry]]:
        text = doc_path.read_text(encoding="utf-8")
        if doc_path.suffix.lower() not in {".srt", ".txt"}:
            return text, []

        entries = SRTParser.parse(text)
        if not entries:
            return text, []
        return SRTParser.to_plaintext(entries, include_timestamp=True), entries

    def _estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text) / 3))

    async def _stage_semantic_segmentation(
        self, text: str, subtitle_entries: List[SubtitleEntry] | None = None
    ) -> List[SemanticSegment]:
        if subtitle_entries:
            lines = [
                f"[{entry.start} -> {entry.end}] {entry.text}" for entry in subtitle_entries
            ]
            return [
                SemanticSegment(
                    title="字幕时间戳分段",
                    start_line=subtitle_entries[0].index if subtitle_entries else 1,
                    end_line=subtitle_entries[-1].index if subtitle_entries else 1,
                    content="\n".join(lines).strip(),
                    source_entries=list(subtitle_entries),
                )
            ]

        lines = text.splitlines()
        if not lines:
            return [SemanticSegment(title="全文", start_line=1, end_line=1, content=text)]

        return [
            SemanticSegment(
                title="全文",
                start_line=1,
                end_line=len(lines),
                content="\n".join(lines).strip(),
            )
        ]

    async def _stage_sub_chunk(
        self,
        segments: List[SemanticSegment],
        source_hint: str | Path | None = None,
    ) -> List[TextChunk]:
        chunks: List[TextChunk] = []
        for segment_idx, segment in enumerate(segments):
            if segment.source_entries:
                chunks.extend(
                    self._chunk_subtitle_entries(
                        segment.source_entries,
                        segment,
                        segment_idx,
                        source_hint=source_hint,
                    )
                )
                continue

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

            for chunk_idx, piece in enumerate(
                self._split_text_by_char_limit(segment.content, self.chunk_size * 3)
            ):
                if not piece.strip():
                    continue
                chunks.append(
                    TextChunk(
                        title=f"{segment.title}-子块{chunk_idx + 1}",
                        content=piece.strip(),
                        start_line=segment.start_line,
                        end_line=segment.end_line,
                        segment_index=segment_idx,
                    )
                )
        return chunks

    def _chunk_subtitle_entries(
        self,
        entries: List[SubtitleEntry],
        segment: SemanticSegment,
        segment_idx: int,
        source_hint: str | Path | None = None,
    ) -> List[TextChunk]:
        if not entries:
            return []

        chunk_char_limit = max(500, self.chunk_size * 3)
        chunks: List[TextChunk] = []
        current_entries: List[SubtitleEntry] = []
        current_length = 0

        def _flush() -> None:
            if not current_entries:
                return
            spans = [
                {
                    "index": entry.index,
                    "start_time": entry.start,
                    "end_time": entry.end,
                    "text": entry.text,
                }
                for entry in current_entries
            ]
            content = "\n".join(
                f"[{entry.start} -> {entry.end}] {entry.text}" for entry in current_entries
            ).strip()
            if not content:
                return
            chunks.append(
                TextChunk(
                    title=f"{segment.title}-子块{len(chunks) + 1}",
                    content=content,
                    start_line=current_entries[0].index,
                    end_line=current_entries[-1].index,
                    segment_index=segment_idx,
                    start_time=current_entries[0].start,
                    end_time=current_entries[-1].end,
                    has_timestamp=True,
                    time_spans=spans,
                )
            )

        for entry in entries:
            line = f"[{entry.start} -> {entry.end}] {entry.text}".strip()
            if not line:
                continue
            next_length = current_length + len(line) + (1 if current_length else 0)
            if current_entries and next_length > chunk_char_limit:
                _flush()
                current_entries = []
                current_length = 0
            current_entries.append(entry)
            current_length += len(line) + (1 if current_length else 0)

        _flush()
        if len(chunks) <= 1 and len(entries) > 200:
            source_name = Path(source_hint).name if source_hint else segment.title
            if source_name == "":
                source_name = segment.title
            self._log(
                Path(source_name),
                f"WARNING: {segment.title} 共 {len(entries)} 条字幕仅分为 {len(chunks)} 个 chunk。"
                f" chunk_size={self.chunk_size} 可能导致结构化结果过于稀疏（目录式输出）。"
                " 建议先将 processing.chunk_size 调整到 10000-60000 后重跑。",
            )
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

    async def _stage_noise_reduction(
        self, chunks: List[TextChunk], source_path: Path
    ) -> List[TextChunk]:
        if not chunks:
            return []

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
                cleaned = await self.llm.generate(prompt, temperature=0.1)
                cleaned = cleaned.strip()
                raw_chunk = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                if not cleaned or len(cleaned) < int(len(raw_chunk) * 0.35):
                    cleaned = raw_chunk
                return TextChunk(
                    title=chunk.title,
                    content=cleaned,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    segment_index=chunk.segment_index,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"清洗分块失败 ({index + 1}/{len(chunks)}): {exc}"
                ) from exc

        return await asyncio.gather(
            *[_clean_chunk(index, chunk) for index, chunk in enumerate(chunks)]
        )

    async def _stage_structure(
        self, cleaned_chunks: List[TextChunk], source_path: Path
    ) -> List[KnowledgePoint]:
        return await self._stage_structure_single_pass(
            cleaned_chunks=cleaned_chunks,
            source_path=source_path,
            has_timestamps=False,
        )

    async def _stage_structure_single_pass(
        self,
        cleaned_chunks: List[TextChunk],
        source_path: Path,
        has_timestamps: bool = False,
        structure_metrics: Dict[str, int] | None = None,
    ) -> List[KnowledgePoint]:
        if not cleaned_chunks:
            raise RuntimeError("结构化输入为空")
        if structure_metrics is None:
            structure_metrics = {
                "fallback_count": 0,
                "retry_count": 0,
                "weak_chunk_count": 0,
            }
        else:
            structure_metrics.setdefault("fallback_count", 0)
            structure_metrics.setdefault("retry_count", 0)
            structure_metrics.setdefault("weak_chunk_count", 0)

        async def _extract_chunk(index: int, chunk: TextChunk) -> List[KnowledgePoint]:
            last_issues: List[str] = []
            for attempt_idx in range(2):
                issue_summary = None if attempt_idx == 0 else "；".join(last_issues)
                prompt = self._build_structure_prompt(
                    chunk,
                    has_timestamps,
                    is_refinement=(attempt_idx > 0),
                    issue_summary=issue_summary,
                )
                try:
                    parsed = await self._extract_points_from_llm(
                        prompt=prompt,
                        chunk=chunk,
                        source_path=source_path,
                        has_timestamps=has_timestamps,
                    )
                    issues = self._validate_structure_points(parsed, chunk, has_timestamps)
                    if not issues:
                        return parsed
                    last_issues = issues
                    structure_metrics["retry_count"] += 1
                    if attempt_idx < 1:
                        self._log(
                            source_path,
                            f"结构化质量不达标，触发二次精提（chunk {index + 1}/{len(cleaned_chunks)}）: {'；'.join(issues)}",
                        )
                        continue

                    structure_metrics["fallback_count"] += 1
                    if has_timestamps and chunk.has_timestamp:
                        structure_metrics["weak_chunk_count"] += 1
                    fallback_evidence: List[str] = []
                    for item in parsed:
                        if item.evidence:
                            fallback_evidence.extend(item.evidence)
                        elif item.content:
                            fallback_evidence.append(item.content[:60])
                    if not fallback_evidence and issue_summary:
                        fallback_evidence.append(issue_summary)
                    self._log(
                        source_path,
                        f"结构化失败回退（chunk {index + 1}/{len(cleaned_chunks)}）: {'；'.join(issues)}",
                    )
                    return self._build_fallback_points(
                        chunk=chunk,
                        source_path=source_path,
                        has_timestamps=has_timestamps,
                        fallback_evidence=fallback_evidence,
                        note=f"结构化质量不达标: {'；'.join(issues)}",
                    )
                except Exception as exc:
                    last_issues = [str(exc)]
                    structure_metrics["retry_count"] += 1
                    if attempt_idx < 1:
                        self._log(
                            source_path,
                            f"结构化异常，触发二次精提（chunk {index + 1}/{len(cleaned_chunks)}）: {exc}",
                        )
                        continue

                    structure_metrics["fallback_count"] += 1
                    if has_timestamps and chunk.has_timestamp:
                        structure_metrics["weak_chunk_count"] += 1
                    self._log(
                        source_path,
                        f"结构化异常回退（chunk {index + 1}/{len(cleaned_chunks)}）: {exc}",
                    )
                    return self._build_fallback_points(
                        chunk=chunk,
                        source_path=source_path,
                        has_timestamps=has_timestamps,
                        fallback_evidence=[f"异常: {exc}"],
                        note=f"结构化失败: {exc}",
                    )

            raise RuntimeError(
                f"结构化分块失败 ({index + 1}/{len(cleaned_chunks)}): 结构化流程异常"
            )

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
            raise RuntimeError("结构化结果为空，未提取到有效知识点")
        return merged_points

    async def _extract_points_from_llm(
        self,
        prompt: str,
        chunk: TextChunk,
        source_path: Path,
        has_timestamps: bool,
    ) -> List[KnowledgePoint]:
        result = await self.llm.generate(
            prompt,
            temperature=0.2,
            extra_payload=self._get_structure_llm_payload(),
        )
        data = self._parse_json_response(result, source_path=source_path)
        raw_points = (
            data.get("points")
            or data.get("knowledge_points")
            or data.get("items")
            or []
        )
        if not isinstance(raw_points, list):
            raise RuntimeError("结构化输出未返回 points 列表")

        parsed: List[KnowledgePoint] = []
        for item in raw_points:
            if not isinstance(item, dict):
                continue
            title = self._sanitize_structure_title(item.get("title", ""))
            content = str(item.get("content", "")).strip()
            if not content:
                continue

            evidence = self._to_text_list(item.get("evidence"))
            time_ranges = self._normalize_time_ranges(
                item.get("time_ranges"), chunk, has_timestamps
            )
            if has_timestamps and not time_ranges and chunk.has_timestamp:
                time_ranges = self._estimate_time_ranges(chunk, evidence)
            if has_timestamps:
                time_ranges = self._dedupe_time_ranges(time_ranges)
                video_note = title or self._derive_fallback_title(chunk, evidence)
            else:
                video_note = title
            parsed.append(
                KnowledgePoint(
                    title=title,
                    content=content,
                    source_file=str(source_path),
                    video_markers=self._normalize_video_markers(
                        time_ranges, source_path=str(source_path), note=video_note
                    ),
                    time_ranges=time_ranges,
                    evidence=evidence,
                )
            )

        return parsed

    def _extract_structure_text(self, chunk: TextChunk) -> str:
        text = str(chunk.content)
        text = re.sub(r"\[[^\]]*?\]", " ", text)
        text = re.sub(r"\d{2}:\d{2}:\d{2},\d{3}", " ", text)
        return re.sub(r"\s+", "", text).strip()

    def _estimate_min_point_count(self, chunk: TextChunk) -> int:
        source_len = len(self._extract_structure_text(chunk))
        if source_len <= 0:
            return 1
        source_tokens = max(1, source_len // 3)
        base_points = max(1, source_tokens // 520)
        if chunk.has_timestamp:
            marker_hint = max(0, str(chunk.content).count("->") // 20)
            base_points = max(base_points, marker_hint)
        return max(1, min(6, base_points))

    def _estimate_min_content_length(self, chunk: TextChunk) -> int:
        source_len = len(self._extract_structure_text(chunk))
        if source_len <= 0:
            return 30
        return max(30, min(240, int(source_len * 0.12)))

    def _estimate_point_content_length(
        self, chunk: TextChunk, point_count: int | None = None
    ) -> int:
        expected_points = max(1, point_count or self._estimate_min_point_count(chunk))
        min_total = self._estimate_min_content_length(chunk)
        return max(28, min(180, max(min_total // expected_points, 40)))

    @staticmethod
    def _to_mapping(payload: Any) -> Dict[str, Any] | None:
        if not isinstance(payload, Mapping):
            return None
        return {str(key): value for key, value in payload.items()}

    def _get_structure_llm_payload(self) -> Dict[str, Any]:
        config = getattr(self.llm, "config", None)
        if not config:
            return {}
        response_format = getattr(config, "response_format", None)
        if not response_format:
            return {}
        normalized = self._to_mapping(response_format)
        if normalized and normalized.get("type") == "json_object":
            return {"response_format": normalized}
        return {"response_format": response_format}

    def _sanitize_structure_title(self, title: Any) -> str:
        title = str(title).strip()
        if not title:
            return ""
        title = re.sub(r"\s+", " ", title)
        title = title.replace("\r", "").replace("\n", " ")
        title = title.strip().strip("-_*`\"'，。；:：,，.。?？!！<>[](){}")
        return title

    def _is_placeholder_title(self, title: str) -> bool:
        placeholder = {
            "未命名知识点",
            "知识点",
            "要点",
            "内容",
            "重点",
            "示例",
            "标题",
            "topic",
            "point",
            "知识点提炼",
            "提炼内容",
        }
        normalized = title.strip().lower()
        return (
            not normalized
            or len(normalized) < 4
            or normalized in placeholder
            or re.fullmatch(r"[0-9一二三四五六七八九十零百千万亿]+", normalized) is not None
            or re.fullmatch(r"\d+", normalized) is not None
            or len(normalized) > 30
        )

    def _validate_structure_points(
        self,
        points: List[KnowledgePoint],
        chunk: TextChunk,
        has_timestamps: bool,
    ) -> List[str]:
        """只拦截结构性异常，并补充最小颗粒度与信息量约束。"""
        issues: List[str] = []
        if not points:
            issues.append("知识点为空: LLM 未返回任何 points")
            return issues

        expected_point_count = self._estimate_min_point_count(chunk)
        if len(points) < expected_point_count:
            issues.append(
                f"知识点数量不足: 当前 {len(points)}，建议 >= {expected_point_count}"
            )

        expected_total_content = self._estimate_min_content_length(chunk)
        actual_total_content = sum(
            len(str(point.content or "").strip()) for point in points
        )
        if actual_total_content < expected_total_content:
            issues.append(
                f"content 过少: {actual_total_content} < {expected_total_content}"
            )
        min_content_per_point = self._estimate_point_content_length(
            chunk, point_count=max(expected_point_count, len(points))
        )

        for index, point in enumerate(points, 1):
            title = self._sanitize_structure_title(point.title)
            point.title = title
            point.content = str(point.content)
            content = point.content.strip()
            if self._is_placeholder_title(title):
                issues.append(f"point{index} 标题无效: {point.title}")
            if not content:
                issues.append(f"point{index} content 为空")
            elif len(content) < min_content_per_point:
                issues.append(
                    f"point{index} content 过短: {len(content)} < {min_content_per_point}"
                )
            if not point.evidence:
                issues.append(f"point{index} evidence 为空")
            if has_timestamps and chunk.has_timestamp and not point.time_ranges:
                issues.append(f"point{index} 缺少 time_ranges")

        return issues

    def _derive_fallback_title(self, chunk: TextChunk, evidence: List[str]) -> str:
        candidates: List[str] = []
        for item in evidence:
            if not item:
                continue
            cleaned = re.sub(r"\[[^\]]*]", "", str(item))
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            cleaned = cleaned.strip("-_*`\"'，。；:：,，.。?？!！<>[](){}")
            if cleaned:
                candidates.append(cleaned)
        if chunk.title:
            normalized_title = re.sub(r"\s+", "", chunk.title).strip()
            if normalized_title and not self._is_placeholder_title(normalized_title):
                candidates.append(normalized_title)

        if candidates:
            raw_title = candidates[0].replace(" ", "")
            if len(raw_title) > 22:
                return f"{raw_title[:19]}..."
            return raw_title

        fallback = re.sub(r"\[[^]]*]", "", str(chunk.content))
        fallback = re.sub(r"\s+", "", fallback).strip()
        if not fallback:
            if chunk.start_time and chunk.end_time:
                return f"{chunk.start_time} 到 {chunk.end_time} 核心内容"
            return "课程片段知识点"
        if chunk.start_time and chunk.end_time:
            return f"{chunk.start_time} 到 {chunk.end_time} {fallback[:12]}..."
        return f"{fallback[:20]}"

    def _build_fallback_content(self, chunk: TextChunk, note: str) -> str:
        normalized = re.sub(r"\s+", " ", str(chunk.content)).strip()
        if len(normalized) > 220:
            normalized = normalized[:220] + "..."
        if note:
            return f"受控降级：{note}。原文定位：{normalized}"
        return f"受控降级输出：{normalized}"

    def _build_fallback_points(
        self,
        chunk: TextChunk,
        source_path: Path,
        has_timestamps: bool,
        note: str,
        fallback_evidence: List[str] | None = None,
    ) -> List[KnowledgePoint]:
        time_ranges: List[Dict[str, Any]] = []
        if has_timestamps and chunk.has_timestamp:
            time_ranges = self._estimate_time_ranges(chunk, [])
            if not time_ranges and chunk.start_time and chunk.end_time:
                time_ranges = [
                    {
                        "start_time": chunk.start_time,
                        "end_time": chunk.end_time,
                        "source": "estimated",
                        "reason": "fallback_full_chunk",
                    }
                ]

        fallback_evidence = fallback_evidence or []
        title = self._derive_fallback_title(chunk, fallback_evidence)
        if not title:
            title = f"{chunk.start_time}-{chunk.end_time}片段"
        return [
            KnowledgePoint(
                title=title,
                content=self._build_fallback_content(chunk, note),
                source_file=str(source_path),
                video_markers=self._normalize_video_markers(
                    time_ranges,
                    source_path=str(source_path),
                    note=title,
                ),
                time_ranges=time_ranges,
                evidence=fallback_evidence[:3] or ([note] if note else []),
            )
        ]

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
                f"- 估计时间段数: {self._count_estimated_time_ranges(points)}",
                "",
                "---",
                "",
            ]
        )

        for idx, point in enumerate(points, 1):
            lines.extend(
                [
                    f"## {idx}. {self._sanitize_structure_title(point.title)}",
                    "",
                    str(point.content).strip(),
                    "",
                ]
            )
            if point.time_ranges:
                lines.append("### 时间范围")
                for time_range in point.time_ranges:
                    start = str(time_range.get("start_time", "")).strip()
                    end = str(time_range.get("end_time", "")).strip()
                    source = str(time_range.get("source", "mapped")).strip()
                    label = "估计" if source == "estimated" else "已映射"
                    lines.append(f"- [{label}] {start} -> {end}")
                lines.append("")
            else:
                lines.append("### 时间范围")
                lines.append("- 无时间戳文件，不输出时间段")
                lines.append("")

        out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return out_path

    async def _stage_video_mark(self, doc: Document, source_path: Path) -> Document:
        if not doc.knowledge_points:
            return doc

        for point in doc.knowledge_points:
            point.video_markers = self._normalize_video_markers(
                point.time_ranges,
                source_path=point.source_file,
                note=point.title or "知识点",
            )
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

    def _build_structure_prompt(
        self,
        chunk: TextChunk,
        has_timestamps: bool,
        is_refinement: bool = False,
        issue_summary: str | None = None,
    ) -> str:
        mode_note = "二次精提（低质量重试）" if is_refinement else "首次提取"
        expected_points = self._estimate_min_point_count(chunk)
        expected_point_len = self._estimate_point_content_length(chunk, expected_points)
        expected_total_len = self._estimate_min_content_length(chunk)
        contract = (
            "你是课程结构化标注器（高级版）。"
            "你的任务是把输入片段转为可直接放入教材的知识点，不允许空泛总结。\n"
            "严格输出 JSON：{\"points\":[...] }，不得输出 Markdown 或解释性文本。\n\n"
            f"当前模式：{mode_note}\n"
            f"当前片段有效字符：{len(self._extract_structure_text(chunk))}\n"
            f"质量约束：建议至少 {expected_points} 条 points，points 总 content 建议不少于 {expected_total_len} 字；"
            f"每条 content 建议不少于 {expected_point_len} 字。\n\n"
            "字段契约：\n"
            '1) points: 列表，不能为空。\n'
            '2) title: 4~28 字，不可为占位词（如“未命名知识点”“知识点1”“要点”等）。\n'
            "3) content: 充实文本，不允许仅一句话+时间戳；应具备定义/条件/步骤/边界/结论中至少两个要素。\n"
            "4) evidence: list[string]，每条至少一项，优先使用原文短句。\n"
            f"5) time_ranges: 有时间输入时可提供；没有时间输入可为空数组。\n\n"
            "负向约束（严禁）：\n"
            "- 不要把多个独立主题压进同一条。\n"
            "- 不要重复标题。\n"
            "- 不要只输出概述性标题，必须有可落教材的可执行内容。\n"
            "- 不要输出无时间输入时才出现无效 title 或空 content。\n\n"
            "输出模板（严格）：\n"
            '{\n  "points": [\n'
            '    {\n'
            '      "title": "知识点标题",\n'
            '      "content": "提炼后的教学文本",\n'
            '      "evidence": ["原文关键短句1", "原文关键短句2"],\n'
            '      "time_ranges": [\n'
            '        {"start_time":"00:10:00,000","end_time":"00:12:15,500","source":"mapped","description":"关键子段"}\n'
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "反例（目录化）：\n"
            '{\n'
            '  "points": [\n'
            '    {"title":"交易技巧", "content":"交易技巧内容很多", "evidence":["交易技巧"]}\n'
            "  ]\n"
            "}\n\n"
            "反例（无证据）：\n"
            '{\n'
            '  "points": [\n'
            '    {"title":"要点", "content":"市场变化很重要", "evidence": []}\n'
            "  ]\n"
            "}\n\n"
            "示例：\n"
            '{\n'
            '  "points": [\n'
            '    {\n'
            '      "title":"突破盘整后的加仓纪律",\n'
            '      "content":"在盘整后突破时先确认 2 根有效 K 线与量能放大，再按既定仓位比例分步进场。若回踩失败并且收盘连续下破，立即撤单并回到 1/3 风险仓位，以保留后续复归弹性。",\n'
            '      "evidence": ["先确认2根有效K线", "量能放大才可加仓"],\n'
            '      "time_ranges": [\n'
            '        {"start_time":"00:02:10,000","end_time":"00:03:40,000","source":"mapped","description":"加仓纪律"}\n'
            '      ]\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )

        if is_refinement and issue_summary:
            contract += (
                "本次是二次精提，请修复以下问题，并且每个问题都要可验证：\n"
                f"{issue_summary}\n"
            )
        elif is_refinement:
            contract += "本次是二次精提：按更细颗粒度重建知识点。\n"

        if has_timestamps:
            contract += (
                "时间段规则：\n"
                "- time_ranges 可多条；当且仅当该点有明确依据时返回。\n"
                "- 每条包含 start_time / end_time / source / description。\n"
                '- start_time 与 end_time 必须为 HH:MM:SS,mmm。\n'
                "- source 只允许 mapped 或 estimated。\n"
                "- 不返回越界时间；时间段与片段边界应一致。\n"
            )
        else:
            contract += "当前无可用时间戳：请返回空数组或不包含 time_ranges。\n"

        contract += (
            f"\n当前片段长度: {len(str(chunk.content))} 字\n\n"
            f"当前片段：\n{str(chunk.content)}\n"
        )

        if has_timestamps:
            contract += f"当前片段时间范围: {chunk.start_time} -> {chunk.end_time}\n"
        return contract

    def _to_text_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, tuple):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            value = value.strip()
            return [value] if value else []
        return []

    def _count_estimated_time_ranges(self, points: List[KnowledgePoint]) -> int:
        count = 0
        for point in points:
            count += sum(1 for item in point.time_ranges if item.get("source") == "estimated")
        return count

    def _normalize_time_ranges(
        self, raw_ranges: Any, chunk: TextChunk, has_timestamps: bool
    ) -> List[Dict[str, Any]]:
        if not has_timestamps:
            return []
        if not isinstance(raw_ranges, list):
            return []

        chunk_start = self._parse_timestamp_seconds(chunk.start_time)
        chunk_end = self._parse_timestamp_seconds(chunk.end_time)
        normalized: List[Dict[str, Any]] = []
        for item in raw_ranges:
            if not isinstance(item, dict):
                continue
            start_time = (
                str(item.get("start_time", "")).strip()
                or str(item.get("start", "")).strip()
            )
            end_time = (
                str(item.get("end_time", "")).strip()
                or str(item.get("end", "")).strip()
            )
            source = str(item.get("source", "estimated")).strip().lower()
            if source not in {"mapped", "estimated"}:
                source = "estimated"
            start_sec = self._parse_timestamp_seconds(start_time)
            end_sec = self._parse_timestamp_seconds(end_time)
            if start_sec is None or end_sec is None:
                continue
            if end_sec < start_sec:
                start_sec, end_sec = end_sec, start_sec
            if chunk_start is not None:
                start_sec = max(start_sec, chunk_start)
            if chunk_end is not None:
                end_sec = min(end_sec, chunk_end)
            if end_sec <= start_sec:
                continue
            normalized.append(
                {
                    "start_time": self._format_timestamp(start_sec),
                    "end_time": self._format_timestamp(end_sec),
                    "source": source,
                    "reason": str(item.get("reason", "")).strip() or source,
                }
            )
        normalized.sort(
            key=lambda item: self._parse_timestamp_seconds(item.get("start_time", ""))
            or 0
        )
        return normalized

    def _estimate_time_ranges(
        self, chunk: TextChunk, evidence: List[str]
    ) -> List[Dict[str, Any]]:
        if not chunk.time_spans:
            if chunk.start_time and chunk.end_time:
                return [
                    {
                        "start_time": chunk.start_time,
                        "end_time": chunk.end_time,
                        "source": "estimated",
                        "reason": "fallback_full_chunk",
                    }
                ]
            return []

        normalized_spans = [
            (idx, self._normalize_text(item["text"]), item["start_time"], item["end_time"])
            for idx, item in enumerate(chunk.time_spans)
        ]
        normalized_evidence = [
            self._normalize_text(text) for text in evidence if self._normalize_text(text)
        ]
        match_indices: List[int] = []
        for idx, span_text, _, _ in normalized_spans:
            for item in normalized_evidence:
                if item and item in span_text:
                    match_indices.append(idx)
                    break

        if not match_indices:
            return [
                {
                    "start_time": chunk.start_time,
                    "end_time": chunk.end_time,
                    "source": "estimated",
                    "reason": "fallback_no_match",
                }
            ] if chunk.start_time and chunk.end_time else []

        time_ranges: List[Dict[str, Any]] = []
        for start_idx, end_idx in self._merge_indices_to_ranges(match_indices):
            time_ranges.append(
                {
                    "start_time": chunk.time_spans[start_idx]["start_time"],
                    "end_time": chunk.time_spans[end_idx]["end_time"],
                    "source": "estimated",
                    "reason": "fallback_by_evidence",
                }
            )
        return time_ranges

    @staticmethod
    def _merge_indices_to_ranges(indices: List[int]) -> List[tuple[int, int]]:
        if not indices:
            return []
        indices = sorted(set(indices))
        ranges: List[tuple[int, int]] = []
        start = indices[0]
        end = indices[0]
        for index in indices[1:]:
            if index == end + 1:
                end = index
            else:
                ranges.append((start, end))
                start = index
                end = index
        ranges.append((start, end))
        return ranges

    def _dedupe_time_ranges(self, time_ranges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for item in time_ranges:
            start_sec = self._parse_timestamp_seconds(str(item.get("start_time", "")))
            end_sec = self._parse_timestamp_seconds(str(item.get("end_time", "")))
            if start_sec is None or end_sec is None:
                continue
            key = (
                self._format_timestamp(start_sec),
                self._format_timestamp(end_sec),
                str(item.get("source", "mapped")).strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            item["start_time"] = self._format_timestamp(start_sec)
            item["end_time"] = self._format_timestamp(end_sec)
            item["source"] = str(item.get("source", "mapped")).strip().lower()
            normalized.append(item)
        normalized.sort(key=lambda item: item["start_time"])
        merged: List[Dict[str, Any]] = []
        for item in normalized:
            if not merged:
                merged.append(item)
                continue
            last = merged[-1]
            item_start = self._parse_timestamp_seconds(item.get("start_time", ""))
            item_end = self._parse_timestamp_seconds(item.get("end_time", ""))
            last_end = self._parse_timestamp_seconds(last.get("end_time", ""))
            if (
                item["source"] == last["source"]
                and item_start is not None
                and last_end is not None
                and item_start <= last_end
            ):
                merged[-1]["end_time"] = self._format_timestamp(
                    max(
                        last_end or 0,
                        item_end or 0,
                    )
                )
            else:
                merged.append(item)
        return merged

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", "", str(text)).strip().lower()

    @staticmethod
    def _parse_timestamp_seconds(value: str) -> Optional[float]:
        value = str(value).strip()
        match = re.match(r"(\d+):(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$", value)
        if not match:
            return None
        hour, minute, second, millis = match.groups()
        h = int(hour)
        m = int(minute)
        s = int(second)
        ms = int((millis or "0").ljust(3, "0")[:3])
        return h * 3600 + m * 60 + s + ms / 1000.0

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        h, remainder = divmod(total_ms, 3600000)
        m, remainder = divmod(remainder, 60000)
        s, ms = divmod(remainder, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _normalize_video_markers(
        self,
        time_ranges: List[Dict[str, Any]],
        source_path: str = "",
        note: str = "",
    ) -> List[Dict[str, str]]:
        markers: List[Dict[str, str]] = []
        source_name = Path(source_path).name if source_path else ""
        fallback_desc = str(note).strip()
        for item in time_ranges:
            start = str(item.get("start_time", "")).strip()
            end = str(item.get("end_time", "")).strip()
            if not start or not end:
                continue
            source = str(item.get("source", "mapped")).strip().lower()
            detail = str(item.get("description", "")).strip() or str(
                item.get("reason", "")
            ).strip()
            detail_lower = detail.lower()
            if detail_lower in {"mapped", "estimated"} or detail_lower.startswith(
                "fallback_"
            ):
                detail = ""
            if not detail:
                detail = fallback_desc
            if not detail:
                detail = source_name
            if len(detail) > 40:
                detail = detail[:37] + "..."
            markers.append(
                {
                    "time": f"{start} -> {end}",
                    "description": detail,
                    "source": source,
                    "source_file": source_path,
                }
            )
        return markers

    def _parse_json_response(
        self, text: str, source_path: Path | str | None = None
    ) -> Dict[str, Any]:
        patterns = [
            r"```json\s*\n(.*?)\n```",
            r"```\s*\n(.*?)\n```",
            r"(\{[\s\S]*\})",
        ]
        errors: List[str] = []

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError as exc:
                    errors.append(f"{pattern}: {exc}")
                    continue

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as exc:
            errors.append(f"raw: {exc}")

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                errors.append(f"window: {exc}")
        preview = text.strip()[:300]
        if source_path:
            self._log(
                Path(source_path) if not isinstance(source_path, Path) else source_path,
                f"JSON 解析失败（{source_path}）：{preview}，异常：{'；'.join(errors)}",
            )
        raise ValueError(
            "LLM返回不可解析JSON：" + text.strip()[:1500]
        )


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
