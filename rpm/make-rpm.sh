#!/bin/bash
set -eu
REPO=$(cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(awk '$1 == "Version:" { print $2 }' "$REPO/rpm/harbour-sailplay.spec")
RELEASE=$(awk '$1 == "Release:" { print $2 }' "$REPO/rpm/harbour-sailplay.spec")
WORK=$(mktemp -d /tmp/sailplay-rpm.XXXXXX)
case "$WORK" in
    /tmp/sailplay-rpm.*) ;;
    *) exit 1 ;;
esac
trap 'rm -rf -- "$WORK"' EXIT
STAGE=$WORK/harbour-sailplay-$VERSION
mkdir -p "$STAGE/rpm/payload" "$STAGE/display-source/carui"
cp -r "$REPO/carplay_proto" "$REPO/android_auto" "$REPO/sailplay_sdk" "$REPO/sdk" "$STAGE/"
cp "$REPO/LICENSE" "$STAGE/"
find "$STAGE/carplay_proto" "$STAGE/android_auto" "$STAGE/sailplay_sdk" "$STAGE/sdk" -type d -name __pycache__ -exec rm -rf {} +
mkdir -p "$STAGE/scripts" "$STAGE/diagnostics"
for name in projection-service.py connection-monitor.py android-auto-phone.py restore-projection-network.py stop-projected-apps.py player-lyrics.py keyboard-server.py wireless-probe.py wireless-phone-advertise.py bluetooth-monitor.py wifi-session-probe.py pulse-capture.py media-control.py reload-audio-policy.py reconnect-car.py prepare-media-compat.py prepare-viewport-compat.py extract-artwork.py inspect-accessory-certificate.py; do
    cp "$REPO/scripts/$name" "$STAGE/scripts/"
done
cp "$REPO/scripts/player-queue.py" "$REPO/scripts/install-system-media-bridge.py" "$STAGE/scripts/"
cp -r "$REPO/rpm/payload/"* "$STAGE/rpm/payload/"
cp -r "$REPO/display-source/carui/translations" "$STAGE/display-source/carui/"
mkdir -p "$STAGE/display-source/communication"
cp "$REPO/display-source/communication/"*.qml "$STAGE/display-source/communication/"
cp "$REPO/rpm/"sailplay-phone* "$REPO/rpm/"sailplay-messages* "$STAGE/rpm/"
cp "$REPO/rpm/"org.sailplay.System.*.service "$STAGE/rpm/"
cp "$REPO/display-source/carui/main.qml" "$REPO/display-source/carui/carui-apps.conf" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/CarPalette.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/WeatherCard.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/WeatherLocationPage.qml" "$REPO/display-source/carui/DashboardInfoCard.qml" "$REPO/display-source/carui/NavigationGuidance.js" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/NavigationCard.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/MapDestinationPanel.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/MapBookmarkIcon.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/ContentPage.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/ContentPane.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/MusicPlayer.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/SystemMediaLibrary.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/PlayerQueue.qml" "$REPO/display-source/carui/SystemMediaQueueBridge.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/LyricsPanel.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/AboutPage.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/AppSelectionPage.qml" "$STAGE/display-source/carui/"
cp "$REPO/display-source/carui/mobile-settings.qml" "$REPO/display-source/carui/harbour-sailplay.png" "$STAGE/display-source/carui/"
cp "$REPO/rpm/harbour-sailplay.desktop" "$STAGE/rpm/"
cp "$REPO/rpm/harbour-sailplay.spec" "$REPO/rpm/sailplay.service" "$STAGE/rpm/"
if [ -f "$REPO/diagnostics/corolla-accessory-key.json" ]; then
    cp "$REPO/diagnostics/corolla-accessory-key.json" "$STAGE/diagnostics/"
else
    sed -i 's# --accessory-key /opt/sailplay/diagnostics/corolla-accessory-key.json##' "$STAGE/rpm/sailplay.service"
fi
cp "$REPO/rpm/sailplay-xpolicy.conf" "$STAGE/rpm/"
cp "$REPO/rpm/50-sailplay.rules" "$STAGE/rpm/"
cp "$REPO/rpm/sailplay-reconnect.service" "$STAGE/rpm/"
python3 - "$STAGE" <<'PY'
import pathlib
import sys

for path in pathlib.Path(sys.argv[1]).rglob('*.py'):
    data = path.read_bytes()
    if b'\r\n' in data:
        path.write_bytes(data.replace(b'\r\n', b'\n'))
PY
cd "$WORK"
tar cjf "harbour-sailplay-$VERSION.tar.bz2" "harbour-sailplay-$VERSION"
rpmbuild -ta --target aarch64 --define 'debug_package %{nil}' --define '__os_install_post %{nil}' "harbour-sailplay-$VERSION.tar.bz2"
test -f "$HOME/rpmbuild/RPMS/aarch64/harbour-sailplay-$VERSION-$RELEASE.aarch64.rpm"
