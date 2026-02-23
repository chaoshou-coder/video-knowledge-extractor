"""
Parallel processing - 并行处理多个文档
"""

import asyncio
import threading
from pathlib import Path
from time import perf_counter
from typing import List, Optional
from .workflow import Document, WorkflowEngine


class ParallelProcessor:
    """并行文档处理器"""

    def __init__(self, engine: WorkflowEngine, max_workers: int = 3):
        self.engine = engine
        self.semaphore = asyncio.Semaphore(max_workers)
        self.results: List[Document] = []
        self.total_files: int = 0
        self.skipped_due_interrupt: int = 0
        self.interrupted: bool = False
        self.errors: List[dict] = []
        self.file_summaries: List[dict] = []

    async def process_directory(
        self,
        dir_path: Path,
        pattern: str = "*.srt",
        stop_event: Optional[threading.Event] = None,
        files: Optional[List[Path]] = None,
    ) -> List[Document]:
        """
        并行处理目录下所有匹配文件

        Args:
            dir_path: 目录路径
            pattern: 文件匹配模式，默认 *.srt
            stop_event: 中断控制
            files: 显式文件列表（传入时跳过目录发现）

        Returns:
            List[Document]: 处理后的文档列表
        """
        # 发现文件
        if files is None:
            discovered = sorted(list(dir_path.glob(pattern)) + list(dir_path.glob("*.txt")))
        else:
            discovered = sorted(files)

        self.total_files = len(discovered)
        self.skipped_due_interrupt = 0
        self.interrupted = False
        self.errors = []
        self.file_summaries = []

        if not discovered:
            print(f"未找到匹配文件: {dir_path}/{pattern}")
            return []

        print(
            f"发现 {len(discovered)} 个文件，开始并行处理 (max_workers={self.semaphore._value})"
        )

        # 并行处理
        tasks = [self._process_with_limit(f, stop_event=stop_event) for f in discovered]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # 过滤异常
        docs = []
        for result in results:
            if result["status"] == "failed":
                self.errors.append(
                    {
                        "path": result["path"],
                        "stage": result["stage"],
                        "error": result["error"],
                        "elapsed_sec": result["elapsed_sec"],
                    }
                )
                self.file_summaries.append(result)
                print(f"[{Path(result['path']).name}] 处理失败 ({result['stage']}): {result['error']}")
            elif result["status"] == "skipped":
                self.skipped_due_interrupt += 1
                self.file_summaries.append(result)
            elif result["status"] == "ok":
                docs.append(result["doc"])
                self.file_summaries.append(result)

        self.interrupted = bool(stop_event and stop_event.is_set())
        if self.skipped_due_interrupt:
            print(f"收到中断信号，跳过 {self.skipped_due_interrupt} 个待处理文件")
        print(
            f"完成: {len(docs)}/{len(discovered)} 个文件（失败 {len(self.errors)}，跳过 {self.skipped_due_interrupt}）"
        )
        return docs

    async def _process_with_limit(
        self, file_path: Path, stop_event: Optional[threading.Event] = None
    ) -> dict:
        """带限流的单文件处理"""
        async with self.semaphore:
            if stop_event and stop_event.is_set():
                print(f"[{file_path.name}] 跳过（收到中断请求）")
                return {
                    "status": "skipped",
                    "path": str(file_path),
                    "elapsed_sec": 0.0,
                    "knowledge_points": 0,
                    "stage": "interrupted",
                    "error": "",
                }

            started = perf_counter()
            try:
                doc = await self.engine.process_document(file_path)
                elapsed = float(doc.metadata.get("total_duration", perf_counter() - started))
                return {
                    "status": "ok",
                    "path": str(file_path),
                    "doc": doc,
                    "elapsed_sec": elapsed,
                    "knowledge_points": len(doc.knowledge_points),
                }
            except Exception as exc:
                stage = str(getattr(exc, "stage", "unknown"))
                detail = str(getattr(exc, "detail", str(exc)))
                return {
                    "status": "failed",
                    "path": str(file_path),
                    "stage": stage,
                    "error": detail,
                    "elapsed_sec": perf_counter() - started,
                    "knowledge_points": 0,
                }

    async def process_with_progress(
        self, dir_path: Path, pattern: str = "*.srt"
    ) -> List[Document]:
        """带进度回调的并行处理 (用于 UI)"""
        return await self.process_directory(dir_path=dir_path, pattern=pattern)
