import os

import pytest

# The tests check the Spanish messages, whatever the language of the machine (libreta.i18n
# reads it on import, and workers inherit it).
os.environ["LIBRETA_LANG"] = "es"


@pytest.fixture(autouse=True)
def no_slow_blocks(monkeypatch):
    """No "elapsed" item unless a test asks for it: on a cold machine a block that imports
    matplotlib may take over SLOW seconds."""
    monkeypatch.setattr("libreta.worker.SLOW", float("inf"))
