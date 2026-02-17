# Contributing to Video Knowledge Extractor

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/yourusername/video-knowledge-extractor.git
cd video-knowledge-extractor
pip install -e ".[full]"
pip install pytest pytest-asyncio
```

## Running Tests

```bash
# Unit tests
pytest tests/test_core.py -v

# BDD tests
python tests/bdd_runner.py
```

## Code Style

- Follow PEP 8
- Use type hints where appropriate
- Add docstrings for public functions

## Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## Report Issues

Please include:
- Python version
- Error message
- Steps to reproduce
