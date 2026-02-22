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
    """字幕解析器（兼容标准 SRT 与时间戳 TXT）"""

    _SRT_TIME_RE = re.compile(
        r"(\d{2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{1,3})"
    )
    _TIMESTAMPED_TEXT_RE = re.compile(
        r"^\[(\d{2}:\d{2}:\d{2}[,.]\d{1,3})\s*->\s*(\d{2}:\d{2}:\d{2}[,.]\d{1,3})\]\s*(.*)$"
    )

    @staticmethod
    def parse_file(file_path: Path) -> List[SubtitleEntry]:
        """解析字幕文件（.srt / .txt）"""
        content = file_path.read_text(encoding="utf-8")
        return SRTParser.parse(content)

    @staticmethod
    def parse(content: str) -> List[SubtitleEntry]:
        """自动检测字幕格式并解析"""
        content = content.strip()
        if not content:
            return []

        if SRTParser._looks_like_timestamped_text(content):
            return SRTParser._parse_timestamped_text(content)

        return SRTParser._parse_srt(content)

    @staticmethod
    def _looks_like_timestamped_text(content: str) -> bool:
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            return bool(SRTParser._TIMESTAMPED_TEXT_RE.match(stripped))
        return False

    @staticmethod
    def _parse_srt(content: str) -> List[SubtitleEntry]:
        """解析标准 SRT（序号 + 时间轴 + 文本块）"""
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
            time_match = SRTParser._SRT_TIME_RE.match(time_line)
            if not time_match:
                continue

            start, end = time_match.groups()
            start = SRTParser._normalize_timestamp(start)
            end = SRTParser._normalize_timestamp(end)

            # 解析文本（可能多行）
            text = " ".join(lines[2:]).strip()

            entries.append(SubtitleEntry(index=index, start=start, end=end, text=text))

        return entries

    @staticmethod
    def _parse_timestamped_text(content: str) -> List[SubtitleEntry]:
        """解析 [start -> end] text 格式"""
        entries: List[SubtitleEntry] = []
        index = 1
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = SRTParser._TIMESTAMPED_TEXT_RE.match(line)
            if not match:
                continue

            start, end, text = match.groups()
            entries.append(
                SubtitleEntry(
                    index=index,
                    start=SRTParser._normalize_timestamp(start),
                    end=SRTParser._normalize_timestamp(end),
                    text=text.strip(),
                )
            )
            index += 1

        return entries

    @staticmethod
    def _normalize_timestamp(ts: str) -> str:
        """统一为 HH:MM:SS,mmm，便于后续展示和处理。"""
        ts = ts.strip().replace(".", ",")
        head, sep, frac = ts.partition(",")
        if not sep:
            return f"{head},000"
        if len(frac) >= 3:
            return f"{head},{frac[:3]}"
        return f"{head},{frac.ljust(3, '0')}"

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


# 兼容旧命名引用
SubtitleParser = SRTParser
