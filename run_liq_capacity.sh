#!/bin/sh
# Entrypoint for the liq_capacity risk-engine run (VPS, systemd timer).
#
# Schedulers start with a minimal PATH that usually omits where `uv`
# installed itself, so we prepend the known locations (same rationale as
# MNEMON's run_mnemon.sh). Output goes to stdout/stderr: systemd captures
# it to journald (`journalctl -u liq-capacity`).
set -eu

cd "$(dirname "$0")"

for d in "$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do
    case ":$PATH:" in
        *":$d:"*) ;;                       # already present
        *) [ -d "$d" ] && PATH="$d:$PATH" ;;
    esac
done
export PATH

exec uv run python -m mrsearch.liq_capacity \
    --data "${MNEMON_DATA:-/home/ubuntu/mnemon/data}" \
    --mnemon-repo "${MNEMON_REPO:-/home/ubuntu/mnemon}"
