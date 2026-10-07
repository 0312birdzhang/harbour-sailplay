#!/bin/bash
# Cross-build every ARM binary the RPM ships. Run INSIDE the SailfishOS SDK:
#
#   sudo ./sdk-chroot -u <sdkuser> sb2 -t SailfishOS-latest-aarch64 \
#       bash /parentroot/mnt/d/code/sfos-carlife/harbour-sailife/rpm/build-arm.sh
#
# Outputs land in rpm/payload/ (git-ignored); rpm/make-rpm.sh packs them.
# x264 is built as a static PIC lib (--disable-asm, like the tablet-native
# build) and linked into carlife-capture, so the RPM carries no x264 runtime
# dependency — the SDK target repos have no x264 package.
set -e
ROOT=/parentroot/mnt/d/code/sfos-carlife/harbour-sailplay
REPO=$ROOT/display-source
PAYLOAD=$ROOT/rpm/payload
mkdir -p "$PAYLOAD"

# --- x264 static (aarch64) --------------------------------------------------
X264_SRC=/home/pc/x264-src
X264_OUT=/home/pc/x264-aarch64
if [ ! -f "$X264_OUT/libx264.a" ]; then
    rm -rf "$X264_SRC"
    mkdir -p "$X264_SRC" "$X264_OUT"
    tar xzf /home/pc/x264.tar.gz -C "$X264_SRC" --strip-components=1
    cd "$X264_SRC"
    ./configure --prefix="$X264_OUT" --enable-static --enable-pic \
        --disable-cli --disable-asm --disable-opencl
    make -j"$(nproc)" libx264.a
    cp libx264.a x264.h x264_config.h "$X264_OUT"/
fi
ls -la "$X264_OUT/libx264.a"

# --- imira-comp (Qt5Compositor virtual 1920x720 screen) ---------------------
cd "$REPO/imira-patches"
CFLAGS=$(pkg-config --cflags Qt5Compositor Qt5Quick Qt5Gui Qt5Core Qt5Widgets)
LIBS=$(pkg-config --libs Qt5Compositor Qt5Quick Qt5Gui Qt5Core Qt5Widgets)
g++ -O2 -std=c++11 -fPIC $CFLAGS imira-comp.cpp $LIBS -lGLESv2 -o "$PAYLOAD/imira-comp"
echo "imira-comp built"

# --- carui (Qt Quick launcher) ----------------------------------------------
cd "$REPO/carui"
rm -f Makefile carui
qmake carui.pro
make -j"$(nproc)"
cp carui "$PAYLOAD/carui"
echo "carui built"

# --- carlife-capture (shm capture + x264 Annex-B encode) --------------------
# The wayland-scanner protocol .c must stay C: compiled by g++ its interface
# symbols get C++-mangled and recorder.cpp (which includes the extern "C"
# client header) cannot resolve them.
cd "$REPO/capture"
gcc -O2 -Iprotocol -c protocol/lipstick-recorder-protocol.c -o protocol.o
g++ -O2 -std=c++11 -pthread \
    -Isrc -Iprotocol -I"$X264_OUT" \
    carlife-capture.cpp shmsource.cpp x264_encoder.cpp \
    src/recorder.cpp src/convert.cpp \
    protocol.o \
    "$X264_OUT/libx264.a" \
    $(pkg-config --libs wayland-client) \
    -lm -ldl -o "$PAYLOAD/carlife-capture"
rm -f protocol.o
echo "carlife-capture built"

file "$PAYLOAD"/*
echo "BUILD_ALL_OK"
