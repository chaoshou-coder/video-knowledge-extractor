#!/usr/bin/env python3
"""
启动脚本
"""
import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

if __name__ == "__main__":
    # 启动 CLI
    from src.cli import main

    main()
