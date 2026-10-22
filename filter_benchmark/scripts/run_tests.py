"""Dependency-free test runner (pytest-compatible naming).

The managed Python on this machine has no pytest and the network blocks
installs, so `python scripts/run_tests.py` discovers all Test* classes and
test_* methods in tests/ and runs them with plain asserts. If pytest IS
available, `pytest tests/ -q` works identically (no fixtures are used).
"""
import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    failures = 0
    total = 0
    for test_file in sorted((ROOT / "tests").glob("test_*.py")):
        mod = load_module(test_file)
        for cls_name in dir(mod):
            cls = getattr(mod, cls_name)
            if not (isinstance(cls, type) and cls_name.startswith("Test")):
                continue
            for meth in dir(cls):
                if not meth.startswith("test_"):
                    continue
                total += 1
                try:
                    getattr(cls(), meth)()
                    print(f"PASS {cls_name}.{meth}")
                except Exception:
                    failures += 1
                    print(f"FAIL {cls_name}.{meth}")
                    traceback.print_exc(limit=3)
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
