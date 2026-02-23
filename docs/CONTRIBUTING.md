# Contributing to Video Knowledge Extractor

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/chaoshou-coder/video-knowledge-extractor.git
cd video-knowledge-extractor
pip install -e .
```

## Running Local Checks

```bash
# Syntax check
python -m compileall src kl.py

# CLI smoke check
python kl.py process examples/sample1.srt --mock -o exports_check
python kl.py process examples/sample2.txt --mock -o exports_check
```

## Code Style

- Follow PEP 8
- Use type hints where appropriate
- Add docstrings for public functions

## Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run local checks
5. Submit a pull request

## Report Issues

Please include:
- Python version
- Error message
- Steps to reproduce
