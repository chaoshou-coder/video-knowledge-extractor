"""
Export formats - Markdown, EPUB, HTML
"""

from pathlib import Path
from typing import List, Dict


class TextbookExporter:
    """教材导出器"""

    def __init__(self, output_dir: str = "./exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def export_markdown(
        self,
        course_name: str,
        chapters: List[Dict],
        transitions: Dict[int, str],
        output_file: str = None,
    ) -> str:
        """
        导出为 Markdown

        chapters: [{"order": 1, "title": "...", "points": [MergedKnowledge]}]
        """
        lines = [f"# {course_name}", "", "## 目录", ""]

        # 目录
        for ch in chapters:
            lines.append(f"{ch['order']}. {ch['title']}")

        lines.extend(["", "---", ""])

        # 章节内容
        for i, ch in enumerate(chapters):
            lines.extend([f"## 第{ch['order']}章 {ch['title']}", ""])

            # 衔接段落
            if i in transitions:
                lines.extend([f"*{transitions[i]}*", ""])

            # 知识点
            for point in ch.get("points", []):
                lines.extend([f"### {point.title}", "", point.content, ""])

                # 视频标记
                if point.video_markers:
                    lines.append("> 📹 **需配合视频学习:**")
                    for marker in point.video_markers:
                        time = marker.get("time", "")
                        desc = marker.get("description", "")
                        lines.append(f"> - [{time}] {desc}")
                    lines.append("")

                lines.append("")

            lines.extend(["---", ""])

        content = "\n".join(lines)

        # 保存
        if output_file is None:
            output_file = f"{course_name}.md"

        output_path = self.output_dir / output_file
        output_path.write_text(content, encoding="utf-8")

        return str(output_path)

    def export_epub(
        self,
        course_name: str,
        chapters: List[Dict],
        transitions: Dict[int, str],
        output_file: str = None,
    ) -> str:
        """导出为 EPUB"""
        try:
            from ebooklib import epub
        except ImportError:
            print("警告: 未安装 ebooklib，跳过 EPUB 导出")
            return ""

        book = epub.EpubBook()
        book.set_identifier(f"knowledge-{course_name}")
        book.set_title(course_name)
        book.set_language("zh")
        book.add_author("AI Knowledge Extractor")

        # 封面
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # 章节
        epub_chapters = []
        for i, ch in enumerate(chapters):
            ch_title = f"第{ch['order']}章 {ch['title']}"

            # 内容 HTML
            content_lines = [f"<h2>{ch_title}</h2>"]

            # 衔接
            if i in transitions:
                content_lines.append(f"<p><em>{transitions[i]}</em></p>")

            # 知识点
            for point in ch.get("points", []):
                content_lines.append(f"<h3>{point.title}</h3>")
                content_lines.append(f'<p>{point.content.replace(chr(10), "<br>")}</p>')

                if point.video_markers:
                    content_lines.append('<div class="video-ref">📹 视频参考:</div>')
                    for marker in point.video_markers:
                        time = marker.get("time", "")
                        desc = marker.get("description", "")
                        content_lines.append(f"<p>[{time}] {desc}</p>")

            # 创建章节
            epub_ch = epub.EpubHtml(
                title=ch_title, file_name=f'chap_{ch["order"]}.xhtml', lang="zh"
            )
            epub_ch.content = "\n".join(content_lines)

            book.add_item(epub_ch)
            epub_chapters.append(epub_ch)

        # 目录
        book.toc = epub_chapters
        book.add_item(epub.EpubNav())

        # 样式
        style = """
        body { font-family: system-ui, sans-serif; line-height: 1.6; }
        h2 { color: #333; border-bottom: 2px solid #007bff; }
        h3 { color: #555; margin-top: 1.5em; }
        .video-ref { background: #f0f0f0; padding: 10px; margin: 10px 0; }
        """
        nav_css = epub.EpubItem(
            uid="style", file_name="style.css", media_type="text/css", content=style
        )
        book.add_item(nav_css)

        #  spine
        book.spine = ["nav"] + epub_chapters

        # 保存
        if output_file is None:
            output_file = f"{course_name}.epub"

        output_path = self.output_dir / output_file
        epub.write_epub(output_path, book)

        return str(output_path)

    def export_html(
        self,
        course_name: str,
        chapters: List[Dict],
        transitions: Dict[int, str],
        output_file: str = None,
    ) -> str:
        """导出为 HTML"""
        html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{course_name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
            color: #333;
        }}
        h1 {{ color: #1a1a1a; }}
        h2 {{ 
            color: #007bff; 
            border-bottom: 2px solid #007bff;
            padding-bottom: 10px;
            margin-top: 40px;
        }}
        h3 {{ color: #555; margin-top: 30px; }}
        .toc {{ background: #f8f9fa; padding: 20px; border-radius: 8px; }}
        .toc ul {{ list-style: none; padding-left: 0; }}
        .toc li {{ padding: 5px 0; }}
        .transition {{ 
            font-style: italic; 
            color: #666; 
            border-left: 3px solid #007bff;
            padding-left: 15px;
            margin: 20px 0;
        }}
        .video-ref {{ 
            background: #f0f7ff; 
            padding: 15px; 
            border-radius: 8px;
            margin: 15px 0;
        }}
        .video-ref::before {{ content: "📹 "; }}
        @media (max-width: 600px) {{
            body {{ padding: 15px; }}
        }}
    </style>
</head>
<body>
    <h1>{course_name}</h1>
    
    <div class="toc">
        <h2>目录</h2>
        <ul>
"""
        # 目录
        for ch in chapters:
            html += f'            <li>{ch["order"]}. {ch["title"]}</li>\n'

        html += """        </ul>
    </div>
    
    <hr>
"""

        # 章节
        for i, ch in enumerate(chapters):
            html += f"""
    <section>
        <h2>第{ch['order']}章 {ch['title']}</h2>
"""
            # 衔接
            if i in transitions:
                html += f'        <p class="transition">{transitions[i]}</p>\n'

            # 知识点
            for point in ch.get("points", []):
                html += f"""
        <h3>{point.title}</h3>
        <p>{point.content.replace(chr(10), "<br>")}</p>
"""
                if point.video_markers:
                    html += '        <div class="video-ref">\n'
                    html += "            <strong>需配合视频学习:</strong><br>\n"
                    for marker in point.video_markers:
                        time = marker.get("time", "")
                        desc = marker.get("description", "")
                        html += f"            [{time}] {desc}<br>\n"
                    html += "        </div>\n"

            html += "    </section>\n"

        html += """
</body>
</html>
"""

        # 保存
        if output_file is None:
            output_file = f"{course_name}.html"

        output_path = self.output_dir / output_file
        output_path.write_text(html, encoding="utf-8")

        return str(output_path)
