import pytest


def pytest_collection_modifyitems(items):
    """Auto-mark tests by directory so ``pytest -m unit`` etc. work."""
    for item in items:
        parts = item.path.parts
        for level in ("unit", "integration", "e2e"):
            if level in parts:
                item.add_marker(getattr(pytest.mark, level))
