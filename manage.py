#!/usr/bin/env python3
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tradingcodex_service.settings")
    from django.core.management import execute_from_command_line

    argv = _prepare_runserver_argv(sys.argv)
    if argv is None:
        return
    execute_from_command_line(argv)


def _prepare_runserver_argv(argv: list[str]) -> list[str] | None:
    if len(argv) < 2 or argv[1] != "runserver":
        return argv
    from tradingcodex_cli.service_autostart import DEFAULT_SERVICE_ADDR, compatible_service_running, service_http_url

    runserver_args = argv[2:]
    if not runserver_args or runserver_args[0].startswith("-"):
        runserver_args = [DEFAULT_SERVICE_ADDR, *runserver_args]
    addr = runserver_args[0]
    if compatible_service_running(addr):
        print(f"TradingCodex service already running at {service_http_url(addr)}")
        return None
    return [argv[0], "runserver", *runserver_args]


if __name__ == "__main__":
    main()
