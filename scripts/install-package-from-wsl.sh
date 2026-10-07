#!/bin/sh
set -eu
: "${SAILPLAY_HOST:?Set SAILPLAY_HOST to the tablet address}"
cd /mnt/d/code/sfos-carlife
sshpass -e scp harbour-sailplay-0.1.0-17.aarch64.rpm "defaultuser@${SAILPLAY_HOST}":/tmp/harbour-sailplay.rpm
sshpass -e ssh "defaultuser@${SAILPLAY_HOST}" sh -s <<'REMOTE'
cat > /tmp/sailplay-install.sh <<'ROOT'
#!/bin/sh
set -eu
: "${SAILPLAY_HOST:?Set SAILPLAY_HOST to the tablet address}"
if [ -d /home/defaultuser/.config/carlife ]; then
    tar czf /home/defaultuser/sailife-config-before-sailplay.tar.gz -C /home/defaultuser/.config carlife
    chmod 600 /home/defaultuser/sailife-config-before-sailplay.tar.gz
fi
systemctl stop sailplay.service 2>/dev/null || :
systemctl stop sailife.service sailife-usb-session.service 2>/dev/null || :
if rpm -q harbour-sailife; then rpm -e harbour-sailife; fi
rpm -Uvh /tmp/harbour-sailplay.rpm
rpm -q harbour-sailplay
if rpm -q harbour-sailife; then echo 'Sailife unexpectedly remains'; exit 1; fi
test -x /opt/sailplay/imira-comp
test -x /opt/sailplay/carui/carui
test -x /opt/sailplay/carlife-capture
python3 -c 'import sys;sys.path.insert(0,"/opt/sailplay");from carplay_proto.display import DisplayPipeline;from carplay_proto.nativecrypto import NativeChaCha;NativeChaCha(bytes(32));import dbus;from gi.repository import GLib;print("Sailplay runtime imports OK")'
systemctl start sailplay.service
systemctl show sailplay.service -p ActiveState -p MainPID
ROOT
chmod 700 /tmp/sailplay-install.sh
REMOTE
sshpass -e ssh -tt "defaultuser@${SAILPLAY_HOST}" devel-su -c /tmp/sailplay-install.sh
