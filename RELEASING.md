# Releasing Jarvis

This checklist keeps releases reproducible. Jarvis is versioned in two places
that must agree:

- `jarvis/__init__.py` → `__version__`
- `setup.py` → `version=`

## 1. Pre-flight

```bash
# Full test suite (no pytest required)
make test

# Syntax check across the tree
make lint

# (optional) run with pytest too
make test-pytest
```

All tests must pass. Update docs if behavior changed:
`CHANGELOG.md`, `RELEASE_NOTES.md`, `PHASE_COMPLETION_MATRIX.md`,
`PROJECT_STATUS.md`, `TASKS.md`.

## 2. Bump the version

Set the new version in both files above (e.g. `1.0.0` → `1.0.1`), then add a
dated section to `CHANGELOG.md`.

## 3. Build the distribution

```bash
python3 -m pip install build
make dist          # -> dist/jarvis_assistant-<version>-py3-none-any.whl (+ .tar.gz)
```

Verify the wheel and sdist contain the web UI and metadata:

```bash
python3 -m zipfile -l dist/jarvis_assistant-*.whl | grep -E "web/|METADATA"
```

## 4. Smoke test the install

```bash
python3 -m venv /tmp/jarvis-venv
/tmp/jarvis-venv/bin/pip install dist/jarvis_assistant-*.whl
/tmp/jarvis-venv/bin/jarvis --version
/tmp/jarvis-venv/bin/jarvis status
```

## 5. Tag and publish

```bash
git add -A
git commit -m "release: v<version>"
git tag -a v<version> -m "Jarvis v<version>"
git push origin main --tags

# Optional: GitHub release
gh release create v<version> dist/* --title "Jarvis v<version>" --notes-file RELEASE_NOTES.md
```

## GitHub-first rule

Per the workspace rules, all work is pushed to GitHub
(`github.com/matif157/jarvis`). Do not leave local-only commits.
