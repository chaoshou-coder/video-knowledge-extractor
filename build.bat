@echo off
echo Building Video Knowledge Extractor...
echo.

REM Install dependencies
pip install -r requirements.txt

REM Build with PyInstaller
pyinstaller --onefile --windowed --name "VideoKnowledgeExtractor" main.py

echo.
echo Build complete!
echo Executable: dist\VideoKnowledgeExtractor.exe
echo.
pause
