#!/usr/bin/env bash
set -euo pipefail

global_args=()
extra_args=()

for arg in "$@"; do
	case "$arg" in
	--check | --dry-run | --verbose | --version)
		global_args+=("$arg")
		;;
	*)
		extra_args+=("$arg")
		;;
	esac
done

uv run formattington "${global_args[@]}" black src test "${extra_args[@]}" &
black_pid=$!

uv run formattington "${global_args[@]}" shfmt ./*.sh &
shfmt_pid=$!

black_status=0
shfmt_status=0
wait "$black_pid" || black_status=$?
wait "$shfmt_pid" || shfmt_status=$?

if [ "$black_status" -ne 0 ]; then
	exit "$black_status"
fi

if [ "$shfmt_status" -ne 0 ]; then
	exit "$shfmt_status"
fi
