# Contributing to WeavyAdmin

Thanks for your interest in contributing!

## Getting Started

1. **Fork** the repository
2. **Clone** your fork locally
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the app to confirm everything works:
   ```bash
   python main.py
   ```

## How to Contribute

### 1. Open an Issue First

Before writing any code, open an issue describing:
- What you want to fix or add
- Why it's needed
- Any approach you have in mind

This avoids wasted effort — we can discuss and align before you spend time coding.

### 2. Fork & Branch

Work on a dedicated branch in your fork:
```bash
git checkout -b feature/your-feature-name
```

### 3. Write Your Code

Follow the existing patterns in the codebase:
- Read `CLAUDE.md` — it documents the architecture, styling rules, and naming conventions
- Each feature lives entirely inside its `features/<name>/` package (view + worker)
- Dialogs go in `dialogs/` — never inside a feature package
- Pure Python business logic goes in `core/` — zero Qt imports there
- All colour constants go in `shared/styles/global_qss.py` (global) or `shared/styles/infra_qss.py` (infra) — never hardcode hex values
- Never call `setStyleSheet()` on individual child widgets — use `setObjectName()` + QSS selectors
- Type hints on all functions including `__init__` and signal handlers

### 4. Code Quality

Run before submitting:
```bash
ruff check --fix .
ruff format .
ruff check .        # must show zero errors
```

Pre-commit hooks run this automatically on `git commit`.

### 5. Open a Pull Request

- Link your PR to the issue it addresses (e.g. `Closes #42`)
- Write a clear description of what changed and why
- Keep PRs focused — one feature or fix per PR
- PRs are reviewed and merged by maintainers only

## What's Welcome

- Bug fixes
- New Weaviate feature views
- UI/UX improvements
- Documentation improvements
- Performance improvements in workers

## What to Avoid

- Breaking the architecture boundaries defined in `CLAUDE.md`
- Importing between `features/` packages — use `shared/` or `core/` for cross-cutting concerns
- Adding dependencies without prior discussion in an issue
- Large refactors without prior issue agreement
- Hardcoded hex colours or inline `setStyleSheet()` calls
- Qt imports anywhere in `core/`
