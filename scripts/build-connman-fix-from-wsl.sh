#!/bin/bash
# Requires the same sfossdk used for Sailplay RPMs; run as WSL root.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
CONNMAN_SOURCE_ROOT=${CONNMAN_SOURCE_ROOT:-/mnt/d/code/sfos-vpn/connman}
GSUPPLICANT_SOURCE=${GSUPPLICANT_SOURCE:-$REPO/diagnostics/connman-rootfix/libgsupplicant}
SDK=${SAILPLAY_SDK:-/srv/sailfishos/sdks/sfossdk}
BASE=fbb2e64b0e996c3102015a7d84098a9691f14bf7
GSUPPLICANT=f6aad2e53b3149bd332f024790ea638f2e0a7c12
mkdir -p "$REPO/diagnostics"
WORK=$(mktemp -d "$REPO/diagnostics/connman-build.XXXXXX")
mkdir -p "$WORK/source" "$WORK/headers"
git -c safe.directory="$CONNMAN_SOURCE_ROOT" -C "$CONNMAN_SOURCE_ROOT" archive "$BASE:connman" | tar -x -C "$WORK/source"
git -c safe.directory="$GSUPPLICANT_SOURCE" -C "$GSUPPLICANT_SOURCE" archive "$GSUPPLICANT:include" | tar -x -C "$WORK/headers"
patch -d "$WORK/source" -p1 < "$REPO/connman-patches/0001-unpublish-removed-services.patch"
printf 'ConnMan source: %s\nlibgsupplicant headers: %s\n' "$BASE" "$GSUPPLICANT" > "$WORK/build-manifest.txt"
cd "$SDK"
./sdk-chroot -u pc sb2 -t SailfishOS-latest-aarch64 bash \
    "/parentroot$REPO/connman-patches/build-in-sdk.sh" "/parentroot$WORK" "/parentroot$REPO"
cp /home/pc/rpmbuild/RPMS/aarch64/sailplay-connman-fix-1.0.0-2.aarch64.rpm "$REPO/../"
printf 'Build sources, test executable and manifest retained: %s\n' "$WORK"
