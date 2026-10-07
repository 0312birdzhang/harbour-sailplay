#!/bin/bash
set -eu
cd /srv/sailfishos/sdks/sfossdk
REPO=/parentroot/mnt/d/code/sfos-carlife/harbour-sailplay
./sdk-chroot -u pc sb2 -t SailfishOS-latest-aarch64 bash "$REPO/rpm/build-arm.sh"
./sdk-chroot -u pc sb2 -t SailfishOS-latest-aarch64 bash "$REPO/rpm/make-rpm.sh"
cp /home/pc/rpmbuild/RPMS/aarch64/harbour-sailplay-0.1.0-17.aarch64.rpm /mnt/d/code/sfos-carlife/
