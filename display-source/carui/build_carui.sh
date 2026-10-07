#!/bin/bash
cd /parentroot/mnt/d/code/sfos-carlife/harbour-sailife/carui
qmake carui.pro 2>&1 | tail -3
make 2>&1 | tail -8
echo CARUI_BUILD_EXIT=$?
ls -la carui 2>&1