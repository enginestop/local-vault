#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT=${1:-release}
mkdir -p "$ROOT/$OUTPUT"
cd "$ROOT"
npm ci
npm run build
cd backend
pyinstaller --noconfirm --clean LocalVault.spec
cyclonedx-py environment --output-file "$ROOT/$OUTPUT/sbom-python.cdx.json"
case "$(uname -s)" in
  Darwin) ARCHIVE="LocalVault-macos-$(uname -m).tar.gz" ;;
  *) ARCHIVE="LocalVault-linux-$(uname -m).tar.gz" ;;
esac
tar -C dist -czf "$ROOT/$OUTPUT/$ARCHIVE" LocalVault
cd "$ROOT/$OUTPUT"
sha256sum "$ARCHIVE" > SHA256SUMS
