#!/usr/bin/env sh
set -eu

PYTHON_VERSION="3.14"
PACKAGE_SPEC="tradingcodex"
WORKSPACE=""
OVERWRITE="0"
RUN_DOCTOR="1"

usage() {
  cat <<'USAGE'
Usage:
  install.sh [options] <workspace>

Options:
  --from <package-spec>  Install from a PyPI name, path, URL, or PEP 508 spec.
  --from-github         Install from monarchjuno/tradingcodex main.
  --python <version>    Python version for uvx. Default: 3.14.
  --overwrite           Pass --overwrite to tcx init.
  --no-doctor           Skip ./tcx doctor after bootstrap.
  -h, --help            Show this help.

Examples:
  install.sh ~/tradingcodex-workspaces/apple-research
  install.sh --from-github ~/tradingcodex-workspaces/apple-research
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --from)
      if [ "$#" -lt 2 ]; then
        echo "install.sh: --from requires a package spec" >&2
        exit 2
      fi
      PACKAGE_SPEC="$2"
      shift 2
      ;;
    --from-github)
      PACKAGE_SPEC="tradingcodex @ git+https://github.com/monarchjuno/tradingcodex.git@main"
      shift
      ;;
    --python)
      if [ "$#" -lt 2 ]; then
        echo "install.sh: --python requires a version" >&2
        exit 2
      fi
      PYTHON_VERSION="$2"
      shift 2
      ;;
    --overwrite)
      OVERWRITE="1"
      shift
      ;;
    --no-doctor)
      RUN_DOCTOR="0"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "install.sh: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [ -n "$WORKSPACE" ]; then
        echo "install.sh: only one workspace path is supported" >&2
        usage >&2
        exit 2
      fi
      WORKSPACE="$1"
      shift
      ;;
  esac
done

if [ -z "$WORKSPACE" ] && [ "$#" -gt 0 ]; then
  WORKSPACE="$1"
  shift
fi

if [ -z "$WORKSPACE" ]; then
  usage >&2
  exit 2
fi

ensure_uvx() {
  if command -v uvx >/dev/null 2>&1; then
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  echo "install.sh: uv/uvx not found; installing uv into the user environment" >&2
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "install.sh: install uv first: https://docs.astral.sh/uv/" >&2
    exit 127
  fi
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  export PATH
  if ! command -v uvx >/dev/null 2>&1 && ! command -v uv >/dev/null 2>&1; then
    echo "install.sh: uv installation finished, but uvx is still not on PATH" >&2
    exit 127
  fi
}

run_uvx() {
  if command -v uvx >/dev/null 2>&1; then
    uvx "$@"
  else
    uv tool run "$@"
  fi
}

ensure_uvx

echo "install.sh: bootstrapping TradingCodex workspace: $WORKSPACE" >&2
echo "install.sh: package spec: $PACKAGE_SPEC" >&2
TRADINGCODEX_MCP_PACKAGE_SPEC="$PACKAGE_SPEC"
export TRADINGCODEX_MCP_PACKAGE_SPEC
UV_NO_CACHE=1
export UV_NO_CACHE

if [ "$OVERWRITE" = "1" ]; then
  run_uvx --isolated --refresh --python "$PYTHON_VERSION" --from "$PACKAGE_SPEC" tcx init "$WORKSPACE" --overwrite
else
  run_uvx --isolated --refresh --python "$PYTHON_VERSION" --from "$PACKAGE_SPEC" tcx init "$WORKSPACE"
fi

if [ "$RUN_DOCTOR" = "1" ]; then
  (cd "$WORKSPACE" && ./tcx doctor)
fi
