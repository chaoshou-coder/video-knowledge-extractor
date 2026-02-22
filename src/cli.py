"""
CLI - 命令行接口（命令模式 + Wizard 模式）
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click

from .clustering import CrossDocumentClusteringSkill
from .export import TextbookExporter
from .fusion import KnowledgeFusionSkill
from .llm_provider import ProviderRegistry
from .parallel import ParallelProcessor
from .srt_parser import SRTParser
from .workflow import MockLLMClient, ProgressTracker, WorkflowEngine

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - py3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


def _load_chunk_size(config_path: Path, default: int = 60000) -> int:
    if not config_path.exists():
        return default

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        processing = data.get("processing", {})
        if not isinstance(processing, dict):
            return default
        chunk_size = int(processing.get("chunk_size", default))
        if chunk_size < 500:
            return default
        return chunk_size
    except Exception:
        return default


def _build_runtime(
    db_path: str,
    config_path: Path,
    mock: bool,
    enable_video_mark: bool,
    output_dir: str,
    split_output_dirs: bool = False,
) -> Tuple[WorkflowEngine, Optional[ProviderRegistry], object]:
    tracker = ProgressTracker(db_path)
    if mock:
        chunk_size = _load_chunk_size(config_path)
        mock_client = MockLLMClient()
        providers = None
        downstream_llm = mock_client
        engine = WorkflowEngine(
            providers=mock_client,
            tracker=tracker,
            enable_video_mark=enable_video_mark,
            chunk_size=chunk_size,
            output_dir=output_dir,
            split_output_dirs=split_output_dirs,
        )
    else:
        providers = ProviderRegistry.from_config(config_path)
        downstream_llm = providers.get()
        engine = WorkflowEngine(
            providers=providers,
            tracker=tracker,
            enable_video_mark=enable_video_mark,
            output_dir=output_dir,
            split_output_dirs=split_output_dirs,
        )
    return engine, providers, downstream_llm


def _print_provider_summary(providers: ProviderRegistry) -> None:
    info = providers.summary()
    base = str(info["api_base"]).replace("https://", "").replace("http://", "")
    click.echo("当前模型配置:")
    click.echo(f"  - model: {info['model']} @ {base}")
    click.echo(f"  - chunk_size(token): {info['chunk_size']}")
    if info.get("provider_only"):
        click.echo(f"  - provider_only: {', '.join(info['provider_only'])}")
    if info.get("provider_ignore"):
        click.echo(f"  - provider_ignore: {', '.join(info['provider_ignore'])}")
    if info.get("provider_order"):
        click.echo(f"  - provider_order: {', '.join(info['provider_order'])}")
    if info.get("provider_allow_fallbacks") is not None:
        click.echo(f"  - provider_allow_fallbacks: {info['provider_allow_fallbacks']}")
    if info.get("provider_require_parameters") is not None:
        click.echo(
            f"  - provider_require_parameters: {info['provider_require_parameters']}"
        )
    if info.get("provider_data_collection") is not None:
        click.echo(f"  - provider_data_collection: {info['provider_data_collection']}")
    if info.get("provider_zdr") is not None:
        click.echo(f"  - provider_zdr: {info['provider_zdr']}")
    if info.get("provider_sort") is not None:
        click.echo(f"  - provider_sort: {info['provider_sort']}")


async def _run_batch_pipeline(
    engine: WorkflowEngine,
    llm_client: object,
    directory: Path,
    workers: int,
    build: bool,
    export_format: str,
    output_dir: str,
) -> Dict[str, object]:
    processor = ParallelProcessor(engine, max_workers=workers)

    click.echo("阶段 1: 处理文档...")
    docs = await processor.process_directory(directory)
    click.echo(f"完成: {len(docs)} 个文件")

    total_points = sum(len(doc.knowledge_points) for doc in docs)
    result: Dict[str, object] = {"docs": docs, "total_points": total_points, "exports": []}

    if not build:
        return result

    click.echo("\n阶段 2: 收集知识点...")
    all_points = []
    for doc in docs:
        all_points.extend(doc.knowledge_points)

    click.echo("阶段 3: 知识融合...")
    fusion = KnowledgeFusionSkill(llm_client)
    merged_points = await fusion.merge_duplicates(all_points)
    click.echo(f"去重后: {len(merged_points)} 个知识点")

    click.echo("\n阶段 4: 课程聚类...")
    clustering = CrossDocumentClusteringSkill(llm_client)
    structure = await clustering.cluster(merged_points)
    click.echo(f"课程: {structure.name}")
    click.echo(f"章节: {len(structure.chapters)} 个")

    click.echo("\n阶段 5: 生成衔接段落...")
    transitions = await fusion.generate_transitions(structure.chapters)

    click.echo("\n阶段 6: 导出教材...")
    exporter = TextbookExporter(output_dir)
    formats = ["markdown", "epub", "html"] if export_format == "all" else [export_format]

    exports: List[str] = []
    for fmt in formats:
        if fmt == "markdown":
            path = exporter.export_markdown(structure.name, structure.chapters, transitions)
        elif fmt == "epub":
            path = exporter.export_epub(structure.name, structure.chapters, transitions)
        elif fmt == "html":
            path = exporter.export_html(structure.name, structure.chapters, transitions)
        else:
            continue

        if path:
            exports.append(path)
            click.echo(f"  [OK] {fmt}: {path}")

    result["exports"] = exports
    return result


def _run_process_flow(
    db_path: str,
    file_path: Path,
    config_path: Path,
    mock: bool,
    enable_video_mark: bool,
    output_dir: Path | None = None,
) -> None:
    target_output_dir = output_dir or Path("./exports")
    engine, providers, _ = _build_runtime(
        db_path=db_path,
        config_path=config_path,
        mock=mock,
        enable_video_mark=enable_video_mark,
        output_dir=str(target_output_dir),
        split_output_dirs=False,
    )
    if mock:
        click.echo("模拟模式: 使用 Mock LLM，不调用外部 API")
    else:
        if providers:
            _print_provider_summary(providers)

    doc = asyncio.run(engine.process_document(file_path))
    processed_chars = int(doc.metadata.get("processed_chars", len(doc.content)))
    extracted_chars = int(
        doc.metadata.get(
            "extracted_chars", sum(len(point.content) for point in doc.knowledge_points)
        )
    )
    click.echo(f"\n共处理 {processed_chars} 字内容")
    click.echo(f"处理完成: {doc.path}")
    click.echo(f"提取知识点: {len(doc.knowledge_points)} 个，共 {extracted_chars} 字")

    stage_durations = doc.metadata.get("stage_durations", {})
    if isinstance(stage_durations, dict):
        stage_labels = [
            ("rule_cleaning", "规则清理"),
            ("semantic_segmentation", "语义分段"),
            ("sub_chunking", "子切分"),
            ("noise_reduction", "清洗"),
            ("structuring", "结构化"),
            ("video_marking", "视频标记"),
        ]
        click.echo("\n阶段耗时:")
        for key, label in stage_labels:
            if key in stage_durations:
                click.echo(f"  - {label}: {float(stage_durations[key]):.2f}s")
    total_duration = float(doc.metadata.get("total_duration", 0.0))
    if total_duration > 0:
        click.echo(f"总耗时: {total_duration:.2f}s")

    cleaned_output = doc.metadata.get("cleaned_output")
    structured_output = doc.metadata.get("structured_output")
    if cleaned_output:
        click.echo(f"\n清洗输出: {cleaned_output}")
    if structured_output:
        click.echo(f"结构化输出: {structured_output}")


def _run_batch_flow(
    db_path: str,
    directory: Path,
    workers: int,
    build: bool,
    export_format: str,
    output_dir: str,
    config_path: Path,
    mock: bool,
    enable_video_mark: bool,
) -> None:
    engine, providers, llm_client = _build_runtime(
        db_path=db_path,
        config_path=config_path,
        mock=mock,
        enable_video_mark=enable_video_mark,
        output_dir=output_dir,
        split_output_dirs=True,
    )
    if mock:
        click.echo("模拟模式: 使用 Mock LLM，不调用外部 API")
    else:
        if providers:
            _print_provider_summary(providers)

    result = asyncio.run(
        _run_batch_pipeline(
            engine=engine,
            llm_client=llm_client,
            directory=directory,
            workers=workers,
            build=build,
            export_format=export_format,
            output_dir=output_dir,
        )
    )

    click.echo(f"\n总知识点: {result['total_points']} 个")
    if build:
        exports = result.get("exports", [])
        if exports:
            click.echo("导出完成。")
        else:
            click.echo("未产生导出文件。")


def _wizard(db_path: str) -> None:
    click.echo("视频知识提取器 - Wizard 模式")
    mode = click.prompt(
        "请选择模式",
        type=click.Choice(["process", "batch"], case_sensitive=False),
        default="process",
    ).lower()

    mock = click.confirm("是否启用 mock 模式（不调用外部 API）？", default=False)
    config_path = Path(
        click.prompt("配置文件路径", type=str, default="config.toml")
    )
    enable_video_mark = click.confirm(
        "是否启用视频标记阶段（会增加一轮 LLM 调用）？",
        default=False,
    )

    if mode == "process":
        file_path = Path(
            click.prompt(
                "请输入文件路径",
                type=click.Path(exists=True, dir_okay=False, path_type=Path),
            )
        )
        _run_process_flow(
            db_path=db_path,
            file_path=file_path,
            config_path=config_path,
            mock=mock,
            enable_video_mark=enable_video_mark,
            output_dir=Path(
                click.prompt(
                    "输出目录",
                    type=str,
                    default="exports",
                )
            ),
        )
        return

    directory = Path(
        click.prompt(
            "请输入目录路径",
            type=click.Path(exists=True, file_okay=False, path_type=Path),
        )
    )
    workers = click.prompt("并行 worker 数", type=int, default=3)
    build = click.confirm("是否执行全流水线并导出教材？", default=True)
    export_format = click.prompt(
        "输出格式",
        type=click.Choice(["markdown", "epub", "html", "all"], case_sensitive=False),
        default="markdown",
    ).lower()
    output_dir = click.prompt("输出目录", type=str, default="./exports")

    _run_batch_flow(
        db_path=db_path,
        directory=directory,
        workers=workers,
        build=build,
        export_format=export_format,
        output_dir=output_dir,
        config_path=config_path,
        mock=mock,
        enable_video_mark=enable_video_mark,
    )


@click.group(invoke_without_command=True)
@click.option("--db", default="knowledge.db", show_default=True, help="数据库路径")
@click.pass_context
def cli(ctx: click.Context, db: str) -> None:
    """视频知识提取器 CLI"""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    if ctx.invoked_subcommand is None:
        _wizard(db)


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--config",
    default="config.toml",
    show_default=True,
    help="LLM 配置文件路径",
)
@click.option("--mock", is_flag=True, help="模拟模式（不调用外部 API）")
@click.option("--video-mark", is_flag=True, help="启用视频标记阶段")
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("./exports"),
    show_default=True,
    help="process 输出目录（会生成 *_cleaned.md 与 *_structured.md）",
)
@click.pass_context
def process(
    ctx: click.Context,
    file_path: Path,
    config: str,
    mock: bool,
    video_mark: bool,
    output: Path,
) -> None:
    """处理单个文件"""
    _run_process_flow(
        db_path=ctx.obj["db"],
        file_path=file_path,
        config_path=Path(config),
        mock=mock,
        enable_video_mark=video_mark,
        output_dir=output,
    )


@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--workers", "-w", default=3, show_default=True, help="并行处理数")
@click.option("--build", "-b", is_flag=True, help="执行聚类/融合/导出全流水线")
@click.option(
    "--format",
    "-f",
    "export_format",
    default="markdown",
    show_default=True,
    type=click.Choice(["markdown", "epub", "html", "all"], case_sensitive=False),
    help="导出格式",
)
@click.option("--output", "-o", default="./exports", show_default=True, help="输出目录")
@click.option(
    "--config",
    default="config.toml",
    show_default=True,
    help="LLM 配置文件路径",
)
@click.option("--mock", is_flag=True, help="模拟模式（不调用外部 API）")
@click.option("--video-mark", is_flag=True, help="启用视频标记阶段")
@click.pass_context
def batch(
    ctx: click.Context,
    directory: Path,
    workers: int,
    build: bool,
    export_format: str,
    output: str,
    config: str,
    mock: bool,
    video_mark: bool,
) -> None:
    """批量处理目录"""
    _run_batch_flow(
        db_path=ctx.obj["db"],
        directory=directory,
        workers=workers,
        build=build,
        export_format=export_format.lower(),
        output_dir=output,
        config_path=Path(config),
        mock=mock,
        enable_video_mark=video_mark,
    )


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """查看处理状态"""
    conn = sqlite3.connect(ctx.obj["db"])
    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'done'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'pending'").fetchone()[0]

    click.echo("文档统计:")
    click.echo(f"  总数: {total}")
    click.echo(f"  完成: {done}")
    click.echo(f"  待处理: {pending}")

    click.echo("\n最近处理:")
    rows = conn.execute(
        "SELECT path, status, stage FROM documents ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    for row in rows:
        click.echo(f"  {row[0]}: {row[1]} ({row[2]})")

    conn.close()


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def parse(file_path: Path) -> None:
    """解析字幕文件（SRT/TXT）"""
    entries = SRTParser.parse_file(file_path)
    click.echo(f"解析到 {len(entries)} 条字幕")
    for entry in entries[:5]:
        click.echo(f"[{entry.start}] {entry.text[:50]}...")


def main() -> None:
    cli()
