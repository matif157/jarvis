# Phase 15 — Release Readiness (v1.0.0)

Status: IMPLEMENTED · UNIT-TESTED · full regression green
Date: 2026-10-17

## Goal
Turn the completed feature set into a coherent, installable, documented
release: consistent versioning, proper packaging, licensing, docs, a
dependency-free test runner, CI, and cleanup.

## Deliverables

### Versioning (unified → 1.0.0)
- `jarvis/__init__.py` → `__version__ = "1.0.0"`.
- `setup.py` → `version="1.0.0"`.
- `jarvis/app.py` → FastAPI app now reports `jarvis.__version__` (was a
  hardcoded `"0.2.0"`), so `GET /api/status` returns the release version.

### Packaging
- `setup.py`: added `license`, classifiers (incl. Python 3.9–3.12),
  `extras_require[dev]` (pytest/build), `project_urls`, `zip_safe=False`,
  version floors on dependencies, `exclude=("tests", "tests.*")`, safe README
  read.
- `pyproject.toml`: `[build-system]` (setuptools>=61, wheel) plus
  `[tool.pytest.ini_options]` and `[tool.ruff]` config. Metadata stays in
  `setup.py` (setuptools-58 compatible on the dev machine) while builds are
  isolated via the PEP 517 backend.
- `MANIFEST.in`: ships `web/`, docs (`README`, `LICENSE`, `CHANGELOG`,
  `RELEASE_NOTES`, `RELEASING`), `.env.example`, `requirements*.txt`,
  `Makefile`, `tests/`, `scripts/`; prunes `data/`, `config/`, `.git`.
- Verified: `python setup.py sdist` includes `web/index.html`, `web/app.js`,
  `web/style.css`, `LICENSE`, `RELEASE_NOTES.md`, `MANIFEST.in`; zero `data/`
  entries.

### Licensing & docs
- `LICENSE` — MIT, © 2026 Muhammad Atif.
- `README.md` — rewritten: features, requirements, install, quickstart, usage
  (chat/serve/workflow/iot/atif), configuration table, security, testing,
  project structure, license.
- `RELEASE_NOTES.md` — v1.0.0 highlights, verification, install, compatibility.
- `RELEASING.md` — pre-flight, version bump, build, smoke test, tag/publish.

### Tooling & CI
- `scripts/run_tests.py` — dependency-free runner (discovers `tests/test_*.py`,
  imports + runs `test_*`, supports filters and `--list`, non-zero exit on
  failure). Works without pytest.
- `Makefile` — `install`, `install-dev`, `run`, `serve`, `chat`, `test`,
  `test-pytest`, `lint`, `build`/`dist`, `clean`/`clean-dist`.
- `.github/workflows/ci.yml` — byte-compile + full suite on Python 3.9–3.12
  (`push`/`pull_request`/`dispatch`).

### Config
- `jarvis/config.py` — optional `.env` loading via `python-dotenv` (guarded),
  making the previously-declared dependency functional.
- `.env.example` — documents server, storage, provider keys/models, Atif URL.

### Cleanup
- Removed stray `test_file.txt`.
- `tests/test_basic.py::test_version` now asserts semver format instead of a
  pinned string (no longer breaks on version bumps).

## Tests
- New `tests/test_phase15_release.py` — 17 offline checks:
  1. `__version__` is semver
  2. setup.py version == package version
  3. required release artifacts exist
  4. MIT LICENSE present
  5. pyproject build-system + tool config
  6. MANIFEST ships web + docs, prunes data
  7. console entry point + python_requires
  8. CI matrix (3.9–3.12)
  9. Makefile targets
  10. CHANGELOG documents phases 9–14
  11. README key sections
  12. `.env.example` documents config
  13. no stray root files
  14. web UI present and wired to `/api/`
  15. runner is pytest-free
  16. `/api/status` reports the release version
  17. registry exposes ≥ 69 tools (currently 69)
- **Full regression: 306 passed, 0 failed, 29 modules.**

## Verification commands
```bash
make test        # 306 passed, 0 failed
make lint        # byte-compile OK
python3 setup.py --version   # 1.0.0
python3 setup.py sdist       # includes web/ + docs, prunes data/
```

## Notes / not done
- `python -m build` (wheel) not run — `build` is not installed locally; sdist
  creation verified instead. The `jarvis` console script also remains
  uninstalled in this environment (`python -m jarvis.cli` works).
- No commit/push performed (per session constraint). Per the workspace
  GitHub-first rule, changes should be committed and pushed.
