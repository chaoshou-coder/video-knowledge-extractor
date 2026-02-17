"""
CLI - 命令行接口
"""

import asyncio
import click
from pathlib import Path
from .workflow import (
    WorkflowEngine,
    ProgressTracker,
    LLMClient,
    MockLLMClient,
)
from .srt_parser import SRTParser


@click.group()
@click.option("--api-key", envvar="KL_API_KEY", help="LLM API Key")
@click.option("--db", default="knowledge.db", help="数据库路径")
@click.pass_context
def cli(ctx, api_key, db):
    """视频知识提取器 - CLI"""
    ctx.ensure_object(dict)
    ctx.obj["tracker"] = ProgressTracker(db)
    ctx.obj["llm"] = LLMClient(api_key=api_key) if api_key else None


@cli.command()
@click.argument("file_path")
@click.option("--output", "-o", help="输出目录")
@click.pass_context
def process(ctx, file_path, output):
    """处理单个文件"""
    tracker = ctx.obj["tracker"]
    llm = ctx.obj["llm"]

    if not llm:
        click.echo("错误: 需要设置 API Key (KL_API_KEY 环境变量或 --api-key)", err=True)
        return

    engine = WorkflowEngine(llm, tracker)

    async def _run():
        doc = await engine.process_document(Path(file_path))
        click.echo(f"处理完成: {doc.path}")
        click.echo(f"提取知识点: {len(doc.knowledge_points)} 个")

        # 输出预览
        for i, point in enumerate(doc.knowledge_points[:3], 1):
            click.echo(f"\n{i}. {point.title}")
            click.echo(f"   {point.content[:100]}...")

    asyncio.run(_run())


@cli.command()
@click.argument("directory")
@click.option("--workers", "-w", default=3, help="并行数")
@click.option("--build", "-b", is_flag=True, help="处理后生成教材")
@click.option(
    "--format", "-f", default="markdown", help="输出格式: markdown/epub/html/all"
)
@click.option("--output", "-o", default="./exports", help="输出目录")
@click.option("--mock", is_flag=True, help="模拟模式 (不调用 API)")
@click.pass_context
def batch(ctx, directory, workers, build, format, output, mock):
    """批量处理目录并生成教材"""
    from .parallel import ParallelProcessor
    from .clustering import CrossDocumentClusteringSkill
    from .fusion import KnowledgeFusionSkill
    from .export import TextbookExporter

    tracker = ctx.obj["tracker"]
    llm = ctx.obj["llm"]

    if not llm and not mock:
        click.echo("错误: 需要设置 API Key (或 --mock 模拟模式)", err=True)
        return

    if mock:
        click.echo("模拟模式: 使用本地规则处理，不调用 LLM")
        llm = MockLLMClient()

    engine = WorkflowEngine(llm, tracker)
    processor = ParallelProcessor(engine, max_workers=workers)

    async def _run():
        # 1. 批量处理文档
        click.echo("阶段 1: 处理文档...")
        docs = await processor.process_directory(Path(directory))
        click.echo(f"完成: {len(docs)} 个文件")

        if not build:
            total_points = sum(len(d.knowledge_points) for d in docs)
            click.echo(f"总知识点: {total_points} 个")
            return

        # 2. 收集所有知识点
        click.echo("\n阶段 2: 知识聚类...")
        all_points = []
        for doc in docs:
            all_points.extend(doc.knowledge_points)

        # 3. 去重融合
        click.echo("阶段 3: 知识融合...")
        fusion = KnowledgeFusionSkill(llm)
        merged_points = await fusion.merge_duplicates(all_points)
        click.echo(f"去重后: {len(merged_points)} 个知识点")

        # 4. 聚类重组
        click.echo("\n阶段 4: 生成课程结构...")
        clustering = CrossDocumentClusteringSkill(llm)
        structure = await clustering.cluster(merged_points)
        click.echo(f"课程: {structure.name}")
        click.echo(f"章节: {len(structure.chapters)} 个")

        # 5. 生成衔接段落
        click.echo("\n阶段 5: 生成衔接段落...")
        transitions = await fusion.generate_transitions(structure.chapters)

        # 6. 导出
        click.echo("\n阶段 6: 导出教材...")
        exporter = TextbookExporter(output)

        formats = ["markdown", "epub", "html"] if format == "all" else [format]

        for fmt in formats:
            try:
                if fmt == "markdown":
                    path = exporter.export_markdown(
                        structure.name, structure.chapters, transitions
                    )
                    click.echo(f"  ✓ Markdown: {path}")
                elif fmt == "epub":
                    path = exporter.export_epub(
                        structure.name, structure.chapters, transitions
                    )
                    if path:
                        click.echo(f"  ✓ EPUB: {path}")
                elif fmt == "html":
                    path = exporter.export_html(
                        structure.name, structure.chapters, transitions
                    )
                    click.echo(f"  ✓ HTML: {path}")
            except Exception as e:
                click.echo(f"  ✗ {fmt}: {e}", err=True)

        click.echo("\n完成！")

    asyncio.run(_run())


@cli.command()
@click.option("--db", default="knowledge.db")
def status(db):
    """查看处理状态"""
    import sqlite3

    conn = sqlite3.connect(db)

    # 统计
    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status = 'done'"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status = 'pending'"
    ).fetchone()[0]

    click.echo("文档统计:")
    click.echo(f"  总数: {total}")
    click.echo(f"  完成: {done}")
    click.echo(f"  待处理: {pending}")

    # 最近处理
    click.echo("\n最近处理:")
    rows = conn.execute(
        "SELECT path, status, stage FROM documents ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    for row in rows:
        click.echo(f"  {row[0]}: {row[1]} ({row[2]})")

    conn.close()


@cli.command()
@click.argument("file_path")
def parse(file_path):
    """解析 SRT 文件（测试）"""
    entries = SRTParser.parse_file(Path(file_path))
    click.echo(f"解析到 {len(entries)} 条字幕")
    for entry in entries[:5]:
        click.echo(f"[{entry.start}] {entry.text[:50]}...")


def main():
    cli()
