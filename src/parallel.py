"""
Parallel processing - 并行处理多个文档
"""

import asyncio
from pathlib import Path
from typing import List
from .workflow import Document, WorkflowEngine


class ParallelProcessor:
    """并行文档处理器"""

    def __init__(self, engine: WorkflowEngine, max_workers: int = 3):
        self.engine = engine
        self.semaphore = asyncio.Semaphore(max_workers)
        self.results: List[Document] = []

    async def process_directory(
        self, dir_path: Path, pattern: str = "*.srt"
    ) -> List[Document]:
        """
        并行处理目录下所有匹配文件

        Args:
            dir_path: 目录路径
            pattern: 文件匹配模式，默认 *.srt

        Returns:
            List[Document]: 处理后的文档列表
        """
        # 发现文件
        files = list(dir_path.glob(pattern))
        files.extend(dir_path.glob("*.txt"))

        if not files:
            print(f"未找到匹配文件: {dir_path}/{pattern}")
            return []

        print(
            f"发现 {len(files)} 个文件，开始并行处理 (max_workers={self.semaphore._value})"
        )

        # 并行处理
        tasks = [self._process_with_limit(f) for f in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 过滤异常
        docs = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"处理失败 {files[i]}: {result}")
            else:
                docs.append(result)

        print(f"完成: {len(docs)}/{len(files)} 个文件")
        return docs

    async def _process_with_limit(self, file_path: Path) -> Document:
        """带限流的单文件处理"""
        async with self.semaphore:
            print(f"  处理: {file_path.name}")
            return await self.engine.process_document(file_path)

    async def process_with_progress(
        self, dir_path: Path, pattern: str = "*.srt"
    ) -> List[Document]:
        """带进度回调的并行处理 (用于 UI)"""
        files = list(dir_path.glob(pattern))
        files.extend(dir_path.glob("*.txt"))

        total = len(files)
        completed = 0

        async def _process_and_track(f: Path) -> Document:
            nonlocal completed
            async with self.semaphore:
                doc = await self.engine.process_document(f)
                completed += 1
                print(f"进度: {completed}/{total} - {f.name}")
                return doc

        tasks = [_process_and_track(f) for f in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return [r for r in results if not isinstance(r, Exception)]
