"""Pytest configuration and shared fixtures.

This module contains pytest configuration and fixtures that are shared
across all test modules.
"""

import sys
from pathlib import Path

import pytest

# Add the project root to the Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def pytest_collection_modifyitems(config, items):
    """Mark tests by directory so ``-m`` filters mean what they say.

    Only one test used to carry ``@pytest.mark.unit``, so ``pytest -m unit``
    selected a single smoke test and a bare ``pytest`` also ran the e2e suite
    (which spawns a subprocess MCP client).  Applying the marker from the path
    keeps individual files unchanged while making the layers real.
    """
    for item in items:
        parts = set(Path(str(item.path)).parts)
        if "e2e" in parts:
            item.add_marker(pytest.mark.e2e)
        elif "integration" in parts:
            item.add_marker(pytest.mark.integration)
        elif "unit" in parts:
            item.add_marker(pytest.mark.unit)


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory path.
    
    Returns:
        Path to the project root directory.
    """
    return PROJECT_ROOT


@pytest.fixture
def sample_documents_dir(project_root: Path) -> Path:
    """Return the sample documents directory path.
    
    Args:
        project_root: The project root directory path.
        
    Returns:
        Path to the sample documents directory.
    """
    return project_root / "tests" / "fixtures" / "sample_documents"


@pytest.fixture
def config_dir(project_root: Path) -> Path:
    """Return the config directory path.
    
    Args:
        project_root: The project root directory path.
        
    Returns:
        Path to the config directory.
    """
    return project_root / "config"
