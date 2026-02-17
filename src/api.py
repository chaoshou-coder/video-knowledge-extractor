"""
API - FastAPI 服务
"""

from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
import json
import sqlite3
from .workflow import ProgressTracker

app = FastAPI(title="视频知识提取器")

# 配置
DB_PATH = "knowledge.db"
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# 挂载静态文件 (Web UI)
app.mount("/static", StaticFiles(directory="web"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """首页 - 返回 Web UI"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>视频知识提取器</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }
        h1 { color: #333; }
        .upload-zone { border: 2px dashed #ccc; padding: 40px; text-align: center; margin: 20px 0; }
        .upload-zone.dragover { background: #f0f0f0; border-color: #333; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
        button:hover { background: #0056b3; }
        #status { margin-top: 20px; padding: 10px; background: #f5f5f5; }
        .file-item { padding: 10px; margin: 5px 0; background: #f9f9f9; border-left: 3px solid #007bff; }
    </style>
</head>
<body>
    <h1>📚 视频知识提取器</h1>
    
    <div class="upload-zone" id="dropZone">
        <p>拖拽 SRT/TXT 文件到此处</p>
        <p>或 <input type="file" id="fileInput" multiple accept=".srt,.txt"></p>
    </div>
    
    <div id="fileList"></div>
    
    <button onclick="startProcess()">开始处理</button>
    
    <div id="status"></div>
    
    <h2>处理状态</h2>
    <div id="progress"></div>
    
    <script>
        let files = [];
        
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const fileList = document.getElementById('fileList');
        
        dropZone.ondragover = (e) => { e.preventDefault(); dropZone.classList.add('dragover'); };
        dropZone.ondragleave = () => dropZone.classList.remove('dragover');
        dropZone.ondrop = (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            files = [...e.dataTransfer.files];
            showFiles();
        };
        
        fileInput.onchange = (e) => {
            files = [...e.target.files];
            showFiles();
        };
        
        function showFiles() {
            fileList.innerHTML = files.map(f => 
                `<div class="file-item">📄 ${f.name}</div>`
            ).join('');
        }
        
        async function startProcess() {
            if (files.length === 0) {
                alert('请先选择文件');
                return;
            }
            
            document.getElementById('status').textContent = '上传中...';
            
            for (const file of files) {
                const formData = new FormData();
                formData.append('file', file);
                
                await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
            }
            
            document.getElementById('status').textContent = '已上传，正在处理...';
            pollProgress();
        }
        
        async function pollProgress() {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            
            document.getElementById('progress').innerHTML = `
                <p>总文档: ${data.total}, 完成: ${data.done}</p>
                <ul>${data.recent.map(r => `<li>${r.path}: ${r.status}</li>`).join('')}</ul>
            `;
            
            if (data.pending > 0) {
                setTimeout(pollProgress, 2000);
            } else {
                document.getElementById('status').textContent = '处理完成！';
            }
        }
    </script>
</body>
</html>
    """


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...), background_tasks: BackgroundTasks = None
):
    """上传文件并后台处理"""
    # 保存文件
    file_path = UPLOAD_DIR / file.filename
    content = await file.read()
    file_path.write_bytes(content)

    # 添加到队列
    tracker = ProgressTracker(DB_PATH)
    tracker.add_document(str(file_path))

    # 后台处理（简化版）
    # 实际应该用队列，这里简化

    return {"status": "uploaded", "path": str(file_path)}


@app.get("/api/status")
async def get_status():
    """获取处理状态"""
    conn = sqlite3.connect(DB_PATH)

    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status = 'done'"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status = 'pending'"
    ).fetchone()[0]

    recent = conn.execute(
        "SELECT path, status, stage FROM documents ORDER BY created_at DESC LIMIT 10"
    ).fetchall()

    conn.close()

    return {
        "total": total,
        "done": done,
        "pending": pending,
        "recent": [{"path": r[0], "status": r[1], "stage": r[2]} for r in recent],
    }


@app.get("/api/points")
async def get_knowledge_points():
    """获取所有知识点"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT title, content, video_markers, source_file FROM knowledge_points LIMIT 100"
    ).fetchall()
    conn.close()

    return [
        {
            "title": r[0],
            "content": r[1][:200],
            "markers": json.loads(r[2]) if r[2] else [],
            "source": r[3],
        }
        for r in rows
    ]
