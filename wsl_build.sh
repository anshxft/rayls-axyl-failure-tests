#!/bin/bash
# Clone Axyl into ~/axyl-lab and build the node binary in WSL, without sudo.
set -euo pipefail
export PATH="$HOME/.cargo/bin:$PATH"
LAB="$HOME/axyl-lab"
mkdir -p "$LAB"; cd "$LAB"

[ -d axyl/.git ] || git clone --depth 1 https://github.com/raylsnetwork/axyl.git
git -C axyl rev-parse HEAD | tee commit.txt

# libclang without root: the official PyPI wheel ships libclang.so
mkdir -p libclang
python3 - <<'PY'
import io, json, urllib.request, zipfile
meta = json.load(urllib.request.urlopen("https://pypi.org/pypi/libclang/json", timeout=60))
url = next(u["url"] for u in meta["urls"] if "manylinux" in u["filename"] and "x86_64" in u["filename"])
print("wheel:", url)
zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=300).read())).extractall("libclang")
PY
SO=$(find "$LAB/libclang" -name 'libclang*.so*' | head -1)
[ -n "$SO" ] || { echo "libclang.so not found"; exit 1; }
export LIBCLANG_PATH="$(dirname "$SO")"
echo "LIBCLANG_PATH=$LIBCLANG_PATH"
# the wheel has no compiler headers (stdarg.h etc.); point bindgen at GCC's
export BINDGEN_EXTRA_CLANG_ARGS="-I$(gcc -print-file-name=include)"

cd axyl
rustc --version || true
export CARGO_BUILD_JOBS=4   # WSL has 7 GB RAM; limit parallel rustc to avoid OOM
time cargo build --release --bin rayls-network
ls -la target/release/rayls-network
echo BUILD_OK
