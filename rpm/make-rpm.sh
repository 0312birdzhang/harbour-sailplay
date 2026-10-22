#!/bin/bash
set -eu
REPO=/parentroot/mnt/d/code/sfos-carlife/harbour-sailplay
WORK=$(mktemp -d /tmp/sailplay-rpm.XXXXXX)
STAGE=$WORK/harbour-sailplay-0.1.1
mkdir -p "$STAGE/rpm/payload" "$STAGE/display-source/carui"
cp -r "$REPO/carplay_proto" "$STAGE/"
find "$STAGE/carplay_proto" -type d -name __pycache__ -exec rm -rf {} +
mkdir -p "$STAGE/scripts" "$STAGE/diagnostics"
for name in wireless-probe.py wireless-phone-advertise.py bluetooth-monitor.py wifi-session-probe.py pulse-capture.py media-control.py reload-audio-policy.py reconnect-car.py prepare-media-compat.py prepare-viewport-compat.py extract-artwork.py; do
    cp "$REPO/scripts/$name" "$STAGE/scripts/"
done
cp "$REPO/diagnostics/corolla-accessory-key.json" "$STAGE/diagnostics/"
cp -r "$REPO/rpm/payload/"* "$STAGE/rpm/payload/"
cp -r "$REPO/display-source/carui/translations" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/main.qml" "$REPO/display-source/carui/carui-apps.conf" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/CarPalette.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/WeatherCard.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/MusicPlayer.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/mobile-settings.qml" "$REPO/display-source/carui/harbour-sailplay.png" "$STAGE/display-source/carui/"
cp "$REPO/rpm/harbour-sailplay.desktop" "$STAGE/rpm/"
cp "$REPO/rpm/harbour-sailplay.spec" "$REPO/rpm/sailplay.service" "$STAGE/rpm/"
cp "$REPO/rpm/sailplay-xpolicy.conf" "$STAGE/rpm/"
cp "$REPO/rpm/50-sailplay.rules" "$STAGE/rpm/"
cp "$REPO/rpm/sailplay-reconnect.service" "$STAGE/rpm/"
cd "$WORK"
tar cjf harbour-sailplay-0.1.1.tar.bz2 harbour-sailplay-0.1.1
rpmbuild -ta --target aarch64 --define 'debug_package %{nil}' --define '__os_install_post %{nil}' harbour-sailplay-0.1.1.tar.bz2
test -f "$HOME/rpmbuild/RPMS/aarch64/harbour-sailplay-0.1.1-44.aarch64.rpm"
