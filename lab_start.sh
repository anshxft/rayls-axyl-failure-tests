#!/bin/bash
# Configure and start the local 4-validator Axyl network. Usage: lab_start.sh 0xTEST_ADDRESS
set -euo pipefail
ADDR="$1"
export PATH="$HOME/.cargo/bin:$PATH"
LAB="$HOME/axyl-lab"
SO=$(find "$LAB/libclang" -name 'libclang*.so*' | head -1)
export LIBCLANG_PATH="$(dirname "$SO")" BINDGEN_EXTRA_CLANG_ARGS="-I$(gcc -print-file-name=include)" CARGO_BUILD_JOBS=4
cd "$LAB/axyl/etc/test-network"

cp .env.example .env
sed -i 's/^NUM_OBSERVERS=.*/NUM_OBSERVERS=0/; s/^LOG_LEVEL=.*/LOG_LEVEL="v"/; s/^COMPILER_THREADS=.*/COMPILER_THREADS="4"/; s/^RAYLS_NETWORK=.*/RAYLS_NETWORK="local"/' .env
cat > accounts.yaml <<EOF
---
"$ADDR":
  balance: "0xD3C21BCECCEDA1000000"
EOF
if [ -d local-validators ]; then ./local-testnet.sh --start; else ./local-testnet.sh --start --dev-funds "$ADDR"; fi
echo LAB_STARTED
