from __future__ import annotations

from pathlib import Path

import pytest

from tradingcodex_cli.__main__ import dispatch_workspace_command


@pytest.mark.parametrize(
    "args",
    [
        ["list", "--json", "--json"],
        ["install", "--local", "first", "--local", "second"],
        ["rollback", "investment-brain-example", "--version", "1.0.0", "--version", "2.0.0"],
    ],
)
def test_investment_brain_cli_rejects_duplicate_options(tmp_path: Path, args: list[str]) -> None:
    with pytest.raises(ValueError, match="option may be supplied only once"):
        dispatch_workspace_command(tmp_path, "investment-brains", args)
