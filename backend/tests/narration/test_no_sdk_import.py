"""The anthropic SDK is an optional dependency, so importing the app must not
need it. This guards the lazy `import anthropic` inside the client constructor:
without it the whole suite stops running on a venv that has not installed the
narration extra — which is the default state of this one."""

from __future__ import annotations

import subprocess
import sys


def test_importing_the_app_does_not_import_the_sdk():
    code = (
        "import sys; import app.main; "
        "assert 'anthropic' not in sys.modules, 'anthropic imported eagerly'; "
        "import app.narration; "
        "assert 'anthropic' not in sys.modules, 'anthropic imported by package'; "
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
