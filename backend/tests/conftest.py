import pytest


# Required for pytest-asyncio to work without per-test markers
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")
