"""
Knowledge fusion - 知识融合与去重
智能去重 + 内容整合 + 衔接生成
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict
from difflib import SequenceMatcher

from .workflow import KnowledgePoint

logger = logging.getLogger(__name__)


@dataclass
class MergedKnowledge:
    """融合后的知识点"""

    title: str
    content: str
    sources: List[str]
    video_markers: List[Dict] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    confidence: float = 1.0  # 融合置信度
    merged_from: int = 1  # 合并了多少个原始知识点

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "content": self.content,
            "sources": self.sources,
            "video_markers": self.video_markers,
            "examples": self.examples,
            "confidence": self.confidence,
            "merged_from": self.merged_from,
        }


@dataclass
class DuplicateGroup:
    """重复知识点组"""

    best_title: str
    indices: List[int]
    similarity_scores: List[float]
    reason: str


class KnowledgeFusionSkill:
    """知识融合 Skill - 智能去重 + 整合"""

    def __init__(self, llm_client, similarity_threshold: float = 0.75):
        self.llm = llm_client
        self.similarity_threshold = similarity_threshold
        logger.info(f"初始化 KnowledgeFusionSkill (threshold={similarity_threshold})")

    async def merge_duplicates(
        self, points: List[KnowledgePoint]
    ) -> List[MergedKnowledge]:
        """
        合并重复知识点 - 三阶段策略

        阶段1: 快速预筛选（基于标题相似度）
        阶段2: LLM 精准确认
        阶段3: 智能合并内容

        Args:
            points: 原始知识点列表

        Returns:
            List[MergedKnowledge]: 融合后的知识点列表
        """
        if not points:
            logger.warning("没有知识点需要融合")
            return []

        if len(points) == 1:
            return [self._to_merged(points[0])]

        logger.info(f"开始融合 {len(points)} 个知识点")

        # 阶段1: 快速预筛选
        candidate_groups = self._find_similar_candidates(points)
        logger.debug(f"找到 {len(candidate_groups)} 个候选重复组")

        # 阶段2: LLM 精准确认
        confirmed_groups = await self._confirm_duplicates(points, candidate_groups)
        logger.info(f"确认 {len(confirmed_groups)} 个重复组")

        # 阶段3: 智能合并
        merged = await self._merge_all_groups(points, confirmed_groups)
        logger.info(f"融合完成: {len(points)} -> {len(merged)} 个知识点")

        return merged

    def _find_similar_candidates(self, points: List[KnowledgePoint]) -> List[List[int]]:
        """
        快速预筛选 - 基于标题和内容相似度

        使用简单的相似度计算快速找出候选重复组
        """
        n = len(points)
        similarity_matrix = [[0.0] * n for _ in range(n)]

        # 计算两两相似度
        for i in range(n):
            for j in range(i + 1, n):
                sim = self._calculate_similarity(points[i], points[j])
                similarity_matrix[i][j] = sim
                similarity_matrix[j][i] = sim

        # 基于相似度构建候选组
        visited = [False] * n
        groups = []

        for i in range(n):
            if visited[i]:
                continue

            # 找出与 i 相似的点
            group = [i]
            visited[i] = True

            for j in range(i + 1, n):
                if (
                    not visited[j]
                    and similarity_matrix[i][j] >= self.similarity_threshold
                ):
                    group.append(j)
                    visited[j] = True

            if len(group) > 1:
                groups.append(group)

        return groups

    def _calculate_similarity(self, p1: KnowledgePoint, p2: KnowledgePoint) -> float:
        """计算两个知识点的相似度"""
        # 标题相似度（加权更高）
        title_sim = SequenceMatcher(None, p1.title.lower(), p2.title.lower()).ratio()

        # 内容相似度（前200字符）
        content_sim = SequenceMatcher(
            None, p1.content[:200].lower(), p2.content[:200].lower()
        ).ratio()

        # 加权平均
        return title_sim * 0.6 + content_sim * 0.4

    async def _confirm_duplicates(
        self, points: List[KnowledgePoint], candidate_groups: List[List[int]]
    ) -> List[DuplicateGroup]:
        """
        使用 LLM 精准确认重复

        分析候选组，确认是否真正重复
        """
        confirmed = []

        for group_indices in candidate_groups:
            if len(group_indices) < 2:
                continue

            # 构建分析提示
            group_points = [points[i] for i in group_indices]
            point_descriptions = [
                f"[{i}] 标题: {p.title}\n    内容: {p.content[:100]}..."
                for i, p in zip(group_indices, group_points)
            ]

            prompt = f"""分析以下知识点，判断它们是否重复或高度相似。

知识点:
{chr(10).join(point_descriptions)}

任务:
1. 判断这些知识点是否重复（描述同一概念）
2. 如果是重复的，选择最佳标题
3. 给出置信度分数 (0.0-1.0)

按 JSON 输出:
{{
  "is_duplicate": true,
  "best_title": "最佳标题",
  "confidence": 0.9,
  "reason": "解释原因"
}}

注意:
- 标题相似但内容不同不算重复
- 同一概念的不同表述算重复
- 置信度 > 0.8 才认为是重复

只输出 JSON:"""

            try:
                result = await self.llm.generate(prompt, temperature=0.2)
                data = self._parse_json_response(result)

                if data.get("is_duplicate", False) and data.get("confidence", 0) > 0.8:
                    confirmed.append(
                        DuplicateGroup(
                            best_title=data.get("best_title", group_points[0].title),
                            indices=group_indices,
                            similarity_scores=[1.0] * len(group_indices),
                            reason=data.get("reason", ""),
                        )
                    )

            except Exception as e:
                logger.error(f"确认重复失败: {e}")
                # 降级：使用第一点的标题
                confirmed.append(
                    DuplicateGroup(
                        best_title=group_points[0].title,
                        indices=group_indices,
                        similarity_scores=[1.0] * len(group_indices),
                        reason="自动合并（LLM确认失败）",
                    )
                )

        return confirmed

    async def _merge_all_groups(
        self, points: List[KnowledgePoint], confirmed_groups: List[DuplicateGroup]
    ) -> List[MergedKnowledge]:
        """合并所有组"""
        merged = []
        used_indices = set()

        for group in confirmed_groups:
            group_points = [points[i] for i in group.indices if i < len(points)]

            if len(group_points) > 1:
                merged_point = await self._merge_group(group_points, group.best_title)
                merged.append(merged_point)
                used_indices.update(group.indices)
            elif len(group_points) == 1:
                merged.append(self._to_merged(group_points[0]))
                used_indices.add(group.indices[0])

        # 添加未分组的知识点
        for i, p in enumerate(points):
            if i not in used_indices:
                merged.append(self._to_merged(p))

        return merged

    async def _merge_group(
        self, points: List[KnowledgePoint], best_title: str
    ) -> MergedKnowledge:
        """
        智能合并一组知识点

        整合多个相似知识点的内容，去重并保留精华
        """
        if len(points) == 1:
            return self._to_merged(points[0])

        # 准备合并内容
        contents = []
        for i, p in enumerate(points[:5]):  # 最多合并5个
            contents.append(f"版本 {i+1}:\n标题: {p.title}\n内容: {p.content[:1000]}")

        prompt = f"""整合以下 {len(points)} 个相似知识点，生成一个完整的版本。

{chr(10).join(contents)}

任务:
1. 合并所有独特信息，删除重复内容
2. 确保逻辑连贯，结构清晰
3. 保留最重要的概念和细节
4. 优化语言表达

输出整合后的完整内容（保持知识点的详细程度）:"""

        try:
            merged_content = await self.llm.generate(prompt, temperature=0.3)

            # 提取核心内容（去除可能的装饰性文字）
            merged_content = self._clean_merged_content(merged_content)

        except Exception as e:
            logger.error(f"内容合并失败: {e}")
            # 降级：连接所有内容
            merged_content = "\n\n".join([p.content for p in points[:3]])

        # 收集所有来源
        all_sources = list(set([p.source_file for p in points]))

        # 收集所有视频标记
        all_markers = []
        for p in points:
            all_markers.extend(p.video_markers)

        # 去重视频标记
        unique_markers = self._deduplicate_markers(all_markers)

        return MergedKnowledge(
            title=best_title,
            content=merged_content,
            sources=all_sources,
            video_markers=unique_markers,
            examples=self._extract_examples(points),
            confidence=min(1.0, 0.7 + len(points) * 0.05),
            merged_from=len(points),
        )

    def _clean_merged_content(self, content: str) -> str:
        """清理合并后的内容"""
        # 去除可能的 "整合后内容:" 等前缀
        prefixes = [
            r"^整合后的内容[:：]\s*",
            r"^合并后的内容[:：]\s*",
            r"^最终版本[:：]\s*",
        ]

        for prefix in prefixes:
            content = re.sub(prefix, "", content, flags=re.IGNORECASE)

        return content.strip()

    def _deduplicate_markers(self, markers: List[Dict]) -> List[Dict]:
        """去重视频标记"""
        seen = set()
        unique = []

        for m in markers:
            key = f"{m.get('time', '')}-{m.get('description', '')[:30]}"
            if key not in seen:
                seen.add(key)
                unique.append(m)

        return unique[:5]  # 限制数量

    def _extract_examples(self, points: List[KnowledgePoint]) -> List[str]:
        """从知识点中提取例题"""
        examples = []
        for p in points:
            # 查找包含"例"、"例题"、"example"的段落
            lines = p.content.split("\n")
            for line in lines:
                if any(
                    kw in line
                    for kw in ["例", "例题", "示例", "例子", "example", "Example"]
                ):
                    if len(line) > 20 and len(line) < 500:
                        examples.append(line.strip())

        return examples[:3]  # 最多3个例题

    async def generate_transitions(self, chapters: List[Dict]) -> Dict[int, str]:
        """
        为章节生成衔接段落

        创建流畅的章节过渡，增强教材连贯性
        """
        if len(chapters) < 2:
            return {}

        logger.info(f"生成 {len(chapters)-1} 个衔接段落")
        transitions = {}

        for i in range(1, len(chapters)):
            prev_ch = chapters[i - 1]
            curr_ch = chapters[i]

            prev_desc = prev_ch.get("description", prev_ch.get("title", ""))
            curr_desc = curr_ch.get("description", curr_ch.get("title", ""))

            prompt = f"""为教材章节之间写一段衔接段落。

上一章 "{prev_ch.get('title', '')}" 的内容:
{prev_desc[:200]}

本章 "{curr_ch.get('title', '')}" 将要介绍:
{curr_desc[:200]}

任务:
写一段 2-3 句话的过渡段落，说明:
1. 上一章的核心收获
2. 本章与上一章的联系
3. 本章的学习价值

要求:
- 语言流畅自然
- 避免过于生硬
- 激发学习兴趣

直接输出段落内容:"""

            try:
                transition = await self.llm.generate(prompt, temperature=0.4)
                transition = self._clean_transition(transition)
                transitions[i] = transition

            except Exception as e:
                logger.error(f"衔接段落生成失败: {e}")
                transitions[i] = (
                    f"接下来我们将学习 {curr_ch.get('title', '下一章内容')}。"
                )

        return transitions

    def _clean_transition(self, text: str) -> str:
        """清理衔接段落"""
        # 去除引号
        text = text.strip().strip('"').strip("'")

        # 去除 "过渡段落:" 等前缀
        prefixes = [
            r"^过渡段落[:：]\s*",
            r"^衔接[:：]\s*",
            r"^段落[:：]\s*",
        ]

        for prefix in prefixes:
            text = re.sub(prefix, "", text, flags=re.IGNORECASE)

        return text.strip()

    def _to_merged(self, point: KnowledgePoint) -> MergedKnowledge:
        """转换为 MergedKnowledge"""
        return MergedKnowledge(
            title=point.title,
            content=point.content,
            sources=[point.source_file],
            video_markers=point.video_markers,
            examples=self._extract_examples([point]),
            confidence=1.0,
            merged_from=1,
        )

    def _parse_json_response(self, text: str) -> Dict:
        """解析 JSON 响应"""
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

        logger.warning(f"无法解析 JSON: {text[:200]}...")
        return {}
