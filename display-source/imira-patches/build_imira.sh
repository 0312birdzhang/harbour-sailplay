#!/bin/bash
cd /parentroot/mnt/d/code/sfos-carlife/harbour-sailife/imira-patches
echo "=== pkg-config probe ==="
pkg-config --list-all 2>/dev/null | grep -iE 'compositor|wayland' | head
CFLAGS=$(pkg-config --cflags Qt5Compositor Qt5Quick Qt5Gui Qt5Core Qt5Widgets 2>&1)
LIBS=$(pkg-config --libs Qt5Compositor Qt5Quick Qt5Gui Qt5Core Qt5Widgets 2>&1)
LIBS="$LIBS -lGLESv2"
echo "CFLAGS=$CFLAGS"
echo "LIBS=$LIBS"
echo "=== compositor headers ==="
ls /usr/include/qt5/QtWaylandCompositor/QWaylandCompositor 2>/dev/null || echo "no QtWaylandCompositor header"
ls /usr/include/qt5/QtCompositor/QWaylandCompositor 2>/dev/null || echo "no QtCompositor header"
find /usr/include/qt5 -name 'QWaylandCompositor' 2>/dev/null | head -3
echo "=== compiling ==="
g++ -O2 -std=c++11 -fPIC $CFLAGS imira-comp.cpp $LIBS -o imira-comp-arm 2>&1
echo "BUILD_EXIT=$?"
ls -la imira-comp-arm 2>&1