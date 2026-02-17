"""
SRT Parser - 字幕解析
"""

import re
from dataclasses import dataclass
from typing import List
from pathlib import Path


@dataclass
class SubtitleEntry:
    """字幕条目"""

    index: int
    start: str  # 00:05:30,000
    end: str
    text: str


class SRTParser:
    """SRT 解析器"""

    @staticmethod
    def parse_file(file_path: Path) -> List[SubtitleEntry]:
        """解析 SRT 文件"""
        content = file_path.read_text(encoding="utf-8")
        return SRTParser.parse(content)

    @staticmethod
    def parse(content: str) -> List[SubtitleEntry]:
        """解析 SRT 内容"""
        entries = []

        # 分割条目（按空行）
        blocks = re.split(r"\n\s*\n", content.strip())

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue

            # 解析序号
            try:
                index = int(lines[0].strip())
            except ValueError:
                continue

            # 解析时间轴
            time_line = lines[1].strip()
            time_match = re.match(
                r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
                time_line,
            )
            if not time_match:
                continue

            start, end = time_match.groups()

            # 解析文本（可能多行）
            text = " ".join(lines[2:]).strip()

            entries.append(SubtitleEntry(index=index, start=start, end=end, text=text))

        return entries

    @staticmethod
    def to_plaintext(
        entries: List[SubtitleEntry], include_timestamp: bool = True
    ) -> str:
        """转为纯文本"""
        lines = []
        for entry in entries:
            if include_timestamp:
                lines.append(f"[{entry.start}] {entry.text}")
            else:
                lines.append(entry.text)
        return "\n".join(lines)
