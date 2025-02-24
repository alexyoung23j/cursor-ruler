import os
import sys
from pathlib import Path

# Add the root directory to Python path so we can import app
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

# Configure pytest-asyncio
pytest_plugins = ["pytest_asyncio"]

def pytest_addoption(parser):
    parser.addini(
        'asyncio_mode',
        'run async tests in "strict" mode',
        default='strict'
    )
    parser.addini(
        'asyncio_default_fixture_loop_scope',
        'default scope for event loop fixtures',
        default='function'
    ) 