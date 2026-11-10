#!/bin/bash
set -eu
cd /srv/sailfishos/sdks/sfossdk
REPO=/parentroot/mnt/d/code/sfos-carlife/harbour-sailplay
SPEC=/mnt/d/code/sfos-carlife/harbour-sailplay/rpm/harbour-sailplay.spec
VERSION=$(awk '$1 == "Version:" { print $2 }' "$SPEC")
RELEASE=$(awk '$1 == "Release:" { print $2 }' "$SPEC")
./sdk-chroot -u pc sb2 -t SailfishOS-latest-aarch64 bash "$REPO/rpm/build-arm.sh"
./sdk-chroot -u pc sb2 -t SailfishOS-latest-aarch64 bash "$REPO/rpm/make-rpm.sh"
cp "/home/pc/rpmbuild/RPMS/aarch64/harbour-sailplay-$VERSION-$RELEASE.aarch64.rpm" /mnt/d/code/sfos-carlife/
