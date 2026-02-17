"""
Cross-document clustering - 跨文档知识点聚类
使用 LLM 进行智能主题聚类
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict

from .workflow import KnowledgePoint

logger = logging.getLogger(__name__)


@dataclass
class TopicCluster:
    """主题聚类"""

    id: str
    title: str
    description: str
    point_indices: List[int] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "point_indices": self.point_indices,
            "keywords": self.keywords,
        }


@dataclass
class CourseStructure:
    """课程结构"""

    name: str
    chapters: List[Dict]
    topics: List[TopicCluster] = field(default_factory=list)
    prerequisites: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "chapters": self.chapters,
            "topics": [t.to_dict() for t in self.topics],
            "prerequisites": self.prerequisites,
        }


class CrossDocumentClusteringSkill:
    """跨文档知识点聚类 Skill - LLM 驱动"""

    def __init__(self, llm_client, max_points_per_batch: int = 50):
        self.llm = llm_client
        self.max_points_per_batch = max_points_per_batch
        logger.info(
            f"初始化 CrossDocumentClusteringSkill (max_points={max_points_per_batch})"
        )

    async def cluster(self, all_points: List[KnowledgePoint]) -> CourseStructure:
        """
        聚类重组知识点 - 两阶段聚类

        阶段1: LLM 识别主题聚类
        阶段2: 构建课程结构（章节 + 顺序）

        Args:
            all_points: 所有文档的知识点列表

        Returns:
            CourseStructure: 重组后的课程结构
        """
        if not all_points:
            logger.warning("没有知识点需要聚类")
            return CourseStructure(name="未命名课程", chapters=[], topics=[])

        logger.info(f"开始聚类 {len(all_points)} 个知识点")

        # 阶段1: 主题识别
        topics = await self._identify_topics(all_points)
        logger.info(f"识别到 {len(topics)} 个主题")

        # 阶段2: 构建课程结构
        structure = await self._build_course_structure(all_points, topics)
        structure.topics = topics

        # 关联知识点到章节
        self._assign_points_to_chapters(structure, all_points)

        logger.info(f"聚类完成: {structure.name} - {len(structure.chapters)} 个章节")
        return structure

    async def _identify_topics(
        self, all_points: List[KnowledgePoint]
    ) -> List[TopicCluster]:
        """
        使用 LLM 识别主题聚类

        分析知识点内容，识别主要主题
        """
        # 分批处理避免上下文过长
        batches = self._create_batches(all_points)
        all_topics = []

        for batch_idx, batch_points in enumerate(batches):
            logger.debug(f"处理批次 {batch_idx + 1}/{len(batches)}")

            # 构建提示
            point_summaries = [
                f"[{i}] {p.title}\n   {p.content[:150]}..."
                for i, p in enumerate(batch_points)
            ]

            prompt = f"""分析以下 {len(batch_points)} 个知识点，识别其中的主题聚类。

知识点列表:
{chr(10).join(point_summaries)}

任务:
1. 识别主要主题（3-10个主题）
2. 为每个主题确定:
   - 主题名称（简洁明确）
   - 主题描述（1-2句话）
   - 包含的知识点索引
   - 关键词（3-5个）

按以下 JSON 格式输出:
{{
  "topics": [
    {{
      "id": "topic_1",
      "title": "主题名称",
      "description": "主题描述",
      "point_indices": [0, 1, 2],
      "keywords": ["关键词1", "关键词2"]
    }}
  ]
}}

注意:
- 一个知识点可以属于多个主题
- 主题应该有明确的边界，避免过度重叠
- 按重要性排序主题

只输出 JSON，不要有其他内容:"""

            try:
                result = await self.llm.generate(prompt, temperature=0.3)
                data = self._parse_json_response(result)

                for topic_data in data.get("topics", []):
                    # 调整索引（如果是分批的）
                    if batch_idx > 0:
                        offset = batch_idx * self.max_points_per_batch
                        topic_data["point_indices"] = [
                            i + offset
                            for i in topic_data.get("point_indices", [])
                            if i < len(batch_points)
                        ]

                    topic = TopicCluster(
                        id=topic_data.get("id", f"topic_{len(all_topics)}"),
                        title=topic_data.get("title", "未命名主题"),
                        description=topic_data.get("description", ""),
                        point_indices=topic_data.get("point_indices", []),
                        keywords=topic_data.get("keywords", []),
                    )
                    all_topics.append(topic)

            except Exception as e:
                logger.error(f"主题识别失败 (批次 {batch_idx}): {e}")
                # 降级：每个知识点作为一个独立主题
                for i, p in enumerate(batch_points):
                    offset = batch_idx * self.max_points_per_batch
                    all_topics.append(
                        TopicCluster(
                            id=f"topic_{offset + i}",
                            title=p.title,
                            description=p.content[:100],
                            point_indices=[offset + i],
                            keywords=[],
                        )
                    )

        # 合并相似主题
        merged_topics = await self._merge_similar_topics(all_topics)
        return merged_topics

    async def _merge_similar_topics(
        self, topics: List[TopicCluster]
    ) -> List[TopicCluster]:
        """合并相似主题"""
        if len(topics) <= 5:
            return topics

        # 构建主题摘要
        topic_summaries = [
            f"{i}. {t.title}\n   关键词: {', '.join(t.keywords)}\n   描述: {t.description[:100]}"
            for i, t in enumerate(topics)
        ]

        prompt = f"""分析以下 {len(topics)} 个主题，识别可以合并的相似主题。

主题列表:
{chr(10).join(topic_summaries)}

任务:
1. 识别标题或关键词高度相似的主题
2. 建议合并方案
3. 返回合并后的主题列表

按 JSON 输出:
{{
  "merged_topics": [
    {{
      "id": "topic_1",
      "title": "合并后标题",
      "description": "合并后描述",
      "original_indices": [0, 2],
      "keywords": ["关键词1", "关键词2"]
    }}
  ]
}}

注意:
- 只有高度相似的主题才合并
- 保持主题数量在 5-10 个
- 未合并的主题保持原样

只输出 JSON:"""

        try:
            result = await self.llm.generate(prompt, temperature=0.2)
            data = self._parse_json_response(result)

            merged = []
            used_indices = set()

            for merge_data in data.get("merged_topics", []):
                indices = merge_data.get("original_indices", [])

                # 收集所有相关知识点索引
                all_point_indices = []
                for idx in indices:
                    if idx < len(topics):
                        all_point_indices.extend(topics[idx].point_indices)
                        used_indices.add(idx)

                merged_topic = TopicCluster(
                    id=merge_data.get("id", f"merged_{len(merged)}"),
                    title=merge_data.get("title", "合并主题"),
                    description=merge_data.get("description", ""),
                    point_indices=list(set(all_point_indices)),
                    keywords=merge_data.get("keywords", []),
                )
                merged.append(merged_topic)

            # 添加未合并的主题
            for i, topic in enumerate(topics):
                if i not in used_indices:
                    merged.append(topic)

            logger.info(f"主题合并: {len(topics)} -> {len(merged)}")
            return merged

        except Exception as e:
            logger.error(f"主题合并失败: {e}")
            return topics

    async def _build_course_structure(
        self, all_points: List[KnowledgePoint], topics: List[TopicCluster]
    ) -> CourseStructure:
        """
        构建课程结构

        基于主题构建章节，确定学习顺序
        """
        # 构建主题摘要
        topic_summaries = [
            f"{i}. {t.title}\n   描述: {t.description[:80]}\n   知识点数: {len(t.point_indices)}"
            for i, t in enumerate(topics)
        ]

        prompt = f"""基于以下 {len(topics)} 个主题，设计教材的章节结构。

主题列表:
{chr(10).join(topic_summaries)}

任务:
1. 将主题组织为教材章节（3-8章）
2. 确定章节顺序（考虑知识依赖关系）
3. 识别章节间的前置关系

按 JSON 输出:
{{
  "course_name": "课程名称（简洁专业）",
  "chapters": [
    {{
      "order": 1,
      "title": "章节标题",
      "topic_ids": ["topic_1", "topic_2"],
      "description": "章节描述",
      "learning_objectives": ["目标1", "目标2"]
    }}
  ],
  "prerequisites": {{
    "章节标题": ["前置章节标题1", "前置章节标题2"]
  }}
}}

注意:
- 章节标题要专业、清晰
- 考虑知识点的逻辑依赖
- 每章包含2-4个相关主题
- 前置关系要合理

只输出 JSON:"""

        try:
            result = await self.llm.generate(prompt, temperature=0.3)
            data = self._parse_json_response(result)

            structure = CourseStructure(
                name=data.get("course_name", "未命名课程"),
                chapters=data.get("chapters", []),
                topics=topics,
                prerequisites=data.get("prerequisites", {}),
            )

            return structure

        except Exception as e:
            logger.error(f"构建课程结构失败: {e}")
            # 降级：每个主题一章
            return CourseStructure(
                name="未命名课程",
                chapters=[
                    {
                        "order": i + 1,
                        "title": t.title,
                        "topic_ids": [t.id],
                        "description": t.description,
                        "learning_objectives": [],
                    }
                    for i, t in enumerate(topics[:8])  # 最多8章
                ],
                topics=topics,
                prerequisites={},
            )

    def _create_batches(
        self, all_points: List[KnowledgePoint]
    ) -> List[List[KnowledgePoint]]:
        """创建处理批次"""
        batches = []
        for i in range(0, len(all_points), self.max_points_per_batch):
            batch = all_points[i : i + self.max_points_per_batch]
            batches.append(batch)
        return batches

    def _assign_points_to_chapters(
        self, structure: CourseStructure, all_points: List[KnowledgePoint]
    ):
        """将知识点关联到章节"""
        for chapter in structure.chapters:
            topic_ids = chapter.get("topic_ids", [])
            chapter_point_indices = set()

            # 收集该章节所有主题的知识点
            for topic in structure.topics:
                if topic.id in topic_ids:
                    chapter_point_indices.update(topic.point_indices)

            # 关联知识点对象
            chapter["points"] = [
                all_points[i]
                for i in sorted(chapter_point_indices)
                if 0 <= i < len(all_points)
            ]

            chapter["point_count"] = len(chapter["points"])

    def _parse_json_response(self, text: str) -> Dict:
        """解析 LLM 返回的 JSON"""
        # 尝试多种提取方式
        patterns = [
            r"```json\s*\n(.*?)\n```",  # Markdown code block
            r"```\s*\n(.*?)\n```",  # Generic code block
            r"(\{[\s\S]*\})",  # Raw JSON
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    continue

        # 尝试直接解析
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # 提取最外层的大括号内容
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning(f"无法解析 JSON 响应: {text[:200]}...")
        return {}
