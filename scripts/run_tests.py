#!/usr/bin/env python3
"""Dependency-free test runner for Jarvis.

Discovers ``tests/test_*.py``, imports each module, and runs every function
named ``test_*``. Works without pytest installed.

Usage:
    python3 scripts/run_tests.py                 # run everything
    python3 scripts/run_tests.py phase13 phase14 # run matching modules
    python3 scripts/run_tests.py --list          # list modules

Exit code is non-zero if any test fails.
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"


class _Sentinel:
    """Fallback object for test functions that expect a fixture arg."""

    def __setattr__(self, *args, **kwargs):  # noqa: D401
        return None


class Skipped(Exception):
    """Raised by a test to report it cannot run on this host.

    A module can also define ``SKIP = "reason"`` at module level to skip the
    whole module (e.g. macOS-only tests running on the Linux CI runner).
    """


def discover(filters):
    modules = sorted(p.stem for p in TESTS_DIR.glob("test_*.py"))
    if filters:
        modules = [m for m in modules if any(f.lower() in m.lower() for f in filters)]
    return modules


def run_module(name):
    passed = failed = skipped = 0
    failures = []
    module = importlib.import_module(f"tests.{name}")
    skip_reason = getattr(module, "SKIP", None)
    if skip_reason:
        return {
            "passed": 0,
            "failed": 0,
            "failures": [],
            "skipped": 0,
            "module_skip": str(skip_reason),
        }
    for func_name, func in inspect.getmembers(module, inspect.isfunction):
        if not func_name.startswith("test_"):
            continue
        try:
            try:
                func()
            except TypeError:
                func(_Sentinel())
            passed += 1
        except Skipped as exc:
            skipped += 1
            print(f"    skipped {name}.{func_name}: {exc}")
        except Exception:  # noqa: BLE001
            failed += 1
            failures.append((func_name, traceback.format_exc()))
    return {
        "passed": passed,
        "failed": failed,
        "failures": failures,
        "skipped": skipped,
        "module_skip": None,
    }


def main(argv):
    filters = [a for a in argv if not a.startswith("-")]
    listing = "--list" in argv
    modules = discover(filters)

    if listing:
        for m in modules:
            print(m)
        return 0

    if not modules:
        print("No test modules matched.")
        return 1

    total_pass = total_fail = total_skip = 0
    start = time.time()
    for name in modules:
        result = run_module(name)
        if result["module_skip"]:
            print(f"[SKIP] {name}: {result['module_skip']}")
            total_skip += 1
            continue
        p = result["passed"]
        f = result["failed"]
        s = result["skipped"]
        total_pass += p
        total_fail += f
        total_skip += s
        status = "OK" if f == 0 else "FAIL"
        suffix = f", {s} skipped" if s else ""
        print(f"[{status}] {name}: {p} passed, {f} failed{suffix}")
        for func_name, tb in result["failures"]:
            print(f"    FAILED {name}.{func_name}")
            indented = "\n".join(f"      {line}" for line in tb.strip().splitlines())
            print(indented)

    elapsed = time.time() - start
    print(f"\n{total_pass} passed, {total_skip} skipped, {total_fail} failed "
          f"in {elapsed:.1f}s ({len(modules)} modules)")
    return 1 if total_fail else 0


if __name__ == "__main__":
    # Ensure the project root is importable when run from anywhere.
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    raise SystemExit(main(sys.argv[1:]))
