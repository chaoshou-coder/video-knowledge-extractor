#!/usr/bin/env python3
"""
启动脚本
"""
import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        # 启动 API 服务
        import uvicorn
        uvicorn.run("src.api:app", host="0.0.0.0", port=8080, reload=True)
    else:
        # 启动 CLI
        from src.cli import main
        main()
