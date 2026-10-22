from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def tmp_path(request):
    path = Path.cwd() / ".pytest-local" / f"{request.node.name}-{uuid4().hex}"
    path.mkdir(parents=True)
    return path
