from __future__ import annotations

import os
import shlex
from collections.abc import Iterable


_SAFE_GIT_CONFIG = (
    "protocol.allow=never",
    "protocol.ext.allow=never",
    "protocol.file.allow=always",
    "protocol.https.allow=always",
    "protocol.ssh.allow=always",
    "core.fsmonitor=false",
)


def isolated_git_environment(*, read_only: bool = False) -> dict[str, str]:
    """Return a Git environment isolated from process-level repository/config overrides."""

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
        and key.upper() not in {"SSH_ASKPASS", "SSH_ASKPASS_REQUIRE"}
    }
    env.update(
        {
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            # Keep SSH-agent authentication available, but do not permit an inherited
            # config, askpass, command, proxy, or local-command override to execute.
            "GIT_SSH_COMMAND": (
                f"ssh -F {shlex.quote(os.devnull)} "
                "-oBatchMode=yes -oClearAllForwardings=yes "
                "-oPermitLocalCommand=no -oProxyCommand=none -oProxyJump=none"
            ),
        }
    )
    if read_only:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def isolated_git_command(arguments: Iterable[str]) -> list[str]:
    """Build a Git command with explicit protocol and executable-helper boundaries."""

    command = ["git"]
    for item in (
        *_SAFE_GIT_CONFIG,
        f"core.attributesFile={os.devnull}",
        f"core.excludesFile={os.devnull}",
    ):
        command.extend(("-c", item))
    command.extend(arguments)
    return command
