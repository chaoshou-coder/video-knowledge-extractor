#!/usr/bin/env python3
"""
Video Knowledge Extractor v2.0
支持本地 Ollama 和 API
"""

import re
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
from pathlib import Path
from src.llm_client import LLMConfig, OllamaClient


class SRTParser:
    """解析 SRT 字幕文件"""
    
    @staticmethod
    def parse(content: str) -> list:
        """返回字幕条目列表"""
        entries = []
        pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?=\n\n|\Z)'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for match in matches:
            seq, start, end, text = match
            text = text.replace('\n', ' ').strip()
            entries.append({'seq': int(seq), 'start': start, 'end': end, 'text': text})
        return entries


class ConfigDialog:
    """配置对话框"""
    
    def __init__(self, parent, current_config=None):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("LLM 配置")
        self.dialog.geometry("400x300")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self.result = current_config or {"preset": "ollama", "api_key": ""}
        self._create_ui()
        
        # 居中显示
        self.dialog.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.dialog.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.dialog.winfo_height()) // 2
        self.dialog.geometry(f"+{x}+{y}")
    
    def _create_ui(self):
        """创建配置界面"""
        frame = ttk.Frame(self.dialog, padding=20)
        frame.pack(fill='both', expand=True)
        
        # LLM 类型选择
        ttk.Label(frame, text="LLM 类型:").pack(anchor='w')
        
        self.preset_var = tk.StringVar(value=self.result.get("preset", "ollama"))
        presets = [
            ("本地 Ollama", "ollama"),
            ("Kimi (Moonshot)", "kimi"),
            ("OpenAI", "openai"),
            ("OpenRouter", "openrouter")
        ]
        
        for text, value in presets:
            ttk.Radiobutton(frame, text=text, variable=self.preset_var, 
                          value=value, command=self._on_preset_change).pack(anchor='w', pady=2)
        
        # API Key 输入
        ttk.Label(frame, text="API Key (API类型需要):").pack(anchor='w', pady=(15, 5))
        
        self.api_key_var = tk.StringVar(value=self.result.get("api_key", ""))
        self.api_key_entry = ttk.Entry(frame, textvariable=self.api_key_var, show='*', width=40)
        self.api_key_entry.pack(fill='x')
        
        # 自定义 Base URL
        ttk.Label(frame, text="自定义 Base URL (可选):").pack(anchor='w', pady=(10, 5))
        self.base_url_var = tk.StringVar(value=self.result.get("base_url", ""))
        ttk.Entry(frame, textvariable=self.base_url_var, width=40).pack(fill='x')
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', pady=20)
        
        ttk.Button(btn_frame, text="确定", command=self._ok).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="取消", command=self._cancel).pack(side='right')
        
        self._on_preset_change()
    
    def _on_preset_change(self):
        """切换预设时更新界面"""
        preset = self.preset_var.get()
        if preset == "ollama":
            self.api_key_entry.config(state='disabled')
        else:
            self.api_key_entry.config(state='normal')
    
    def _ok(self):
        """确认"""
        self.result = {
            "preset": self.preset_var.get(),
            "api_key": self.api_key_var.get(),
            "base_url": self.base_url_var.get() or None
        }
        self.dialog.destroy()
    
    def _cancel(self):
        """取消"""
        self.result = None
        self.dialog.destroy()
    
    def show(self):
        """显示对话框并等待结果"""
        self.dialog.wait_window()
        return self.result


class MainWindow:
    """主窗口"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("视频知识提取器 v2.0")
        self.root.geometry("1000x700")
        
        self.current_file = None
        self.llm_config = {"preset": "ollama", "api_key": ""}
        self.llm_client = None
        
        self._create_ui()
        self._init_llm()
    
    def _create_ui(self):
        """创建界面"""
        # 顶部工具栏
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(toolbar, text="打开文件", command=self._open_file).pack(side='left', padx=5)
        ttk.Button(toolbar, text="提取知识", command=self._extract).pack(side='left', padx=5)
        ttk.Button(toolbar, text="保存结果", command=self._save).pack(side='left', padx=5)
        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=10)
        ttk.Button(toolbar, text="LLM配置", command=self._config_llm).pack(side='left', padx=5)
        
        self.llm_label = ttk.Label(toolbar, text="LLM: 本地 Ollama")
        self.llm_label.pack(side='right', padx=5)
        
        self.file_label = ttk.Label(toolbar, text="未选择文件")
        self.file_label.pack(side='right', padx=20)
        
        # 左右分栏
        paned = ttk.PanedWindow(self.root, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=10, pady=5)
        
        # 左侧：原文
        left_frame = ttk.LabelFrame(paned, text="原始文本")
        self.source_text = scrolledtext.ScrolledText(left_frame, wrap='word', font=('Consolas', 10))
        self.source_text.pack(fill='both', expand=True, padx=5, pady=5)
        paned.add(left_frame, weight=1)
        
        # 右侧：结果
        right_frame = ttk.LabelFrame(paned, text="结构化知识")
        self.result_text = scrolledtext.ScrolledText(right_frame, wrap='word', font=('Consolas', 10))
        self.result_text.pack(fill='both', expand=True, padx=5, pady=5)
        paned.add(right_frame, weight=1)
        
        # 状态栏
        self.status = ttk.Label(self.root, text="就绪 | 使用本地 Ollama (默认)")
        self.status.pack(fill='x', padx=10, pady=5)
    
    def _init_llm(self):
        """初始化 LLM"""
        try:
            self.llm_client = OllamaClient()
            # 测试连接
            import urllib.request
            urllib.request.urlopen("http://localhost:11434", timeout=2)
            self.status.config(text="就绪 | Ollama 已连接")
        except:
            self.status.config(text="就绪 | Ollama 未运行，请配置其他 LLM")
    
    def _config_llm(self):
        """配置 LLM"""
        dialog = ConfigDialog(self.root, self.llm_config)
        result = dialog.show()
        
        if result:
            self.llm_config = result
            preset_name = LLMConfig.PRESETS.get(result['preset'], {}).get('name', result['preset'])
            self.llm_label.config(text=f"LLM: {preset_name}")
            
            # 创建客户端
            try:
                kwargs = {}
                if result.get('base_url'):
                    kwargs['base_url'] = result['base_url']
                
                self.llm_client = LLMConfig.create_client(
                    result['preset'],
                    api_key=result.get('api_key'),
                    **kwargs
                )
                self.status.config(text=f"就绪 | 已切换到 {preset_name}")
            except Exception as e:
                messagebox.showerror("配置错误", str(e))
    
    def _open_file(self):
        """打开文件"""
        filepath = filedialog.askopenfilename(
            filetypes=[("字幕文件", "*.srt;*.txt"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        
        try:
            path = Path(filepath)
            
            if path.suffix.lower() == '.srt':
                content = path.read_text(encoding='utf-8')
                entries = SRTParser.parse(content)
                text = '\n'.join([f"[{e['start']}] {e['text']}" for e in entries])
            else:
                text = path.read_text(encoding='utf-8')
            
            self.current_file = filepath
            self.source_text.delete('1.0', 'end')
            self.source_text.insert('1.0', text[:10000])
            self.file_label.config(text=path.name)
            self.status.config(text=f"已加载: {len(text)} 字符")
            
        except Exception as e:
            messagebox.showerror("错误", f"加载失败: {e}")
    
    def _extract(self):
        """提取知识"""
        if not self.current_file:
            messagebox.showwarning("提示", "请先打开文件")
            return
        
        if not self.llm_client:
            messagebox.showwarning("提示", "请先配置 LLM")
            return
        
        try:
            self.status.config(text="正在提取知识...")
            self.root.update()
            
            source = self.source_text.get('1.0', 'end')
            
            # 调用 LLM
            result = self.llm_client.extract_knowledge(source)
            
            # 生成 Markdown
            markdown = self._generate_markdown(result)
            
            self.result_text.delete('1.0', 'end')
            self.result_text.insert('1.0', markdown)
            
            topic = result.get('topic', '提取完成')
            concepts = len(result.get('concepts', []))
            points = len(result.get('key_points', []))
            self.status.config(text=f"完成 | 主题: {topic[:30]}... | {concepts} 概念, {points} 要点")
            
        except Exception as e:
            messagebox.showerror("错误", f"提取失败: {e}")
            self.status.config(text=f"错误: {str(e)[:50]}")
    
    def _generate_markdown(self, result: dict) -> str:
        """生成 Markdown"""
        lines = [
            f"# {result.get('topic', '知识提取结果')}",
            "",
            "## 关键概念",
            ""
        ]
        
        for concept in result.get('concepts', []):
            lines.append(f"- {concept}")
        
        lines.extend(["", "## 重要知识点", ""])
        
        for i, point in enumerate(result.get('key_points', []), 1):
            lines.append(f"{i}. {point}")
        
        lines.extend([
            "",
            "## 总结",
            "",
            result.get('summary', ''),
            "",
            "---",
            f"*生成时间: {Path(__file__).stem}*"
        ])
        
        return '\n'.join(lines)
    
    def _save(self):
        """保存结果"""
        if not self.result_text.get('1.0', 'end').strip():
            messagebox.showwarning("提示", "没有内容可保存")
            return
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("JSON", "*.json"), ("文本", "*.txt")]
        )
        if not filepath:
            return
        
        try:
            content = self.result_text.get('1.0', 'end')
            Path(filepath).write_text(content, encoding='utf-8')
            self.status.config(text=f"已保存: {Path(filepath).name}")
            messagebox.showinfo("成功", "文件已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")


def main():
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()


if __name__ == '__main__':
    main()
