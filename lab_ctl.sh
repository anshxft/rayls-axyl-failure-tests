#!/bin/bash
# Crash or restart one local validator. Usage: lab_ctl.sh kill|start <index 0-3>
#   addr   prints "index execution_address" lines from each validator's node-info
export PATH="$HOME/.cargo/bin:$PATH"
SO=$(find "$HOME/axyl-lab/libclang" -name 'libclang*.so*' | head -1)
export LIBCLANG_PATH="$(dirname "$SO")" BINDGEN_EXTRA_CLANG_ARGS="-I$(gcc -print-file-name=include)" CARGO_BUILD_JOBS=4
SELF="$(realpath "$0")"
cd "$HOME/axyl-lab/axyl/etc/test-network" || exit 1
V=local-validators
case "$1" in
  kill)  # SIGKILL on purpose: a crash, with no graceful shutdown
    P="$V/validator-$(($2 + 1)).pid"; kill -9 "$(cat "$P")" && rm -f "$P" && echo "killed validator index $2" ;;
  start)
    tmux new-window -d -t lab "bash '$SELF' _run $2; exec sleep 86400"
    echo "restart requested for validator index $2" ;;
  _run)
    ./local-testnet.sh --start-validator "$2" > "/tmp/restart_$2.log" 2>&1 ;;
  term)  # graceful stop: SIGTERM, wait for exit
    P="$V/validator-$(($2 + 1)).pid"; PID="$(cat "$P")"; kill "$PID"; while kill -0 "$PID" 2>/dev/null; do sleep 1; done; rm -f "$P"; echo "stopped validator index $2" ;;
  reset)  # wipe the local lab network and start a fresh genesis
    tmux kill-server 2>/dev/null; killall -9 rayls-network 2>/dev/null; sleep 2; rm -rf "$V"
    tmux new-session -d -s lab "bash '$(dirname "$SELF")/lab_start.sh' $2 > /tmp/lab_start.log 2>&1; exec sleep 86400"; echo reset-started ;;
  mismatches)
    grep -a -c "Execution-consensus hash mismatch" "$V/validator-$(($2 + 1)).log" ;;
  addr)
    for i in 0 1 2 3; do printf "%s " "$i"; grep -m1 -i -E "execution_address" "$V/validator-$((i + 1))/node-info.yaml" | awk '{print $NF}'; done ;;
esac
