# 开发检查脚本
# 在提交前运行，确保代码质量

echo "=========================================="
echo "Running development checks..."
echo "=========================================="

# 1. Lint 检查
echo ""
echo "1. Running ruff..."
ruff check src/ tests/ --fix
if [ $? -ne 0 ]; then
    echo "❌ Ruff check failed"
    exit 1
fi
echo "✅ Ruff passed"

# 2. 格式化检查
echo ""
echo "2. Running black..."
black src/ tests/
echo "✅ Black formatted"

# 3. 再次检查确保全部通过
echo ""
echo "3. Final lint check..."
ruff check src/ tests/
if [ $? -ne 0 ]; then
    echo "❌ Final lint check failed"
    exit 1
fi
echo "✅ Final lint passed"

# 4. 运行测试
echo ""
echo "4. Running tests..."
python3 -m pytest tests/test_core.py -v
if [ $? -ne 0 ]; then
    echo "❌ Tests failed"
    exit 1
fi
echo "✅ Tests passed"

echo ""
echo "=========================================="
echo "✅ All checks passed! Ready to commit."
echo "=========================================="
