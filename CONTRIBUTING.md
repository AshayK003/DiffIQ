# Contributing to DiffIQ

Thanks for your interest in contributing. This document covers the practical details.

## Getting Started

```bash
git clone https://github.com/AshayK003/DiffIQ.git
cd DiffIQ
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows
pip install -e ".[dev]"
```

Verify everything works:

```bash
pytest tests/ -v             # all tests pass
streamlit run app.py         # dashboard launches
```

## Development Workflow

1. Create a branch from `master`: `git checkout -b feature/my-change`
2. Make your changes
3. Add or update tests
4. Run `pytest tests/ -v` — all tests must pass
5. Commit and push
6. Open a pull request

## What to Work On

Check [open issues](https://github.com/AshayK003/DiffIQ/issues) for planned work. [Good First Issues](https://github.com/AshayK003/DiffIQ/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) are tagged for new contributors.

### Assignment Process

- Comment on an issue to claim it before starting work
- I'll assign you within 24h
- First-come-first-served — if two PRs arrive for the same issue, I merge the assignee's and close the duplicate with context

## Code Conventions

### Python

- Follow existing style in the file you're editing
- Use `logging` module for debug/info output
- Keep imports sorted: stdlib, third-party, local
- Type hints are encouraged but not required

### Architecture

- Core logic lives in `src/`
- Streamlit UI is in `app.py`
- Tests mirror the source structure in `tests/`

### Testing

- Test files go in `tests/`
- Name tests `test_<module>.py`
- Use `pytest` fixtures from `conftest.py`
- Write behavior-focused tests, not implementation tests

### Coverage Reports

Coverage reports upload as CI artifacts on every push. Download them:

1. Go to the **Actions** tab on GitHub
2. Select the latest workflow run
3. Scroll to **Artifacts** section
4. Download `coverage-report-html.zip`

To generate locally:

```bash
pytest tests/ --cov=src --cov-report=html
# Open htmlcov/index.html in your browser
```

## Commit Messages

Use short imperative descriptions:

```
add filing classification for audit reports
fix PDF extraction on multi-page documents
add sector filter to dashboard
improve error handling for BSE API timeouts
```

## Pull Requests

- Keep PRs focused — one change per PR (target ≤200 lines changed)
- Include a description of what changed and why
- Reference related issues
- Small PRs get reviewed and merged faster

## Questions?

Open an [issue](https://github.com/AshayK003/DiffIQ/issues/new) or start a discussion on GitHub.
