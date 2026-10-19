#!/bin/bash
# Run through sdk-chroot/sb2, with the workspace visible under /parentroot.
set -euo pipefail
WORK=$1
REPO=$2
cd "$WORK/source"
autoreconf -fi
./configure --prefix=/usr --libdir=/usr/lib64 --sysconfdir=/etc --localstatedir=/var \
    --with-version=1.40+git26.6.sailplay1 \
    --enable-ethernet=builtin --disable-wifi --enable-bluetooth=builtin \
    --disable-openconnect --disable-openvpn --disable-vpnc --disable-l2tp \
    --disable-pptp --disable-openfortivpn --disable-wireguard \
    --enable-loopback=builtin --enable-pacrunner=builtin \
    --enable-sailfish-vpn-access=builtin --disable-client --enable-test \
    --enable-sailfish-gps --enable-sailfish-wakeup-timer \
    --enable-sailfish-debuglog --enable-sailfish-ofono \
    --enable-sailfish-usb-tethering --enable-sailfish-developer-mode \
    --enable-sailfish-wifi --enable-sailfish-access --enable-sailfish-counters \
    --enable-globalproxy --disable-gadget --disable-wispr \
    --with-systemdunitdir=/usr/lib/systemd/system --enable-systemd \
    --with-tmpfilesdir=/usr/lib/tmpfiles.d runstatedir=/run \
    --enable-blacklist-monitor --enable-clat --with-firewall=iptables \
    --with-dns-backend=systemd-resolved
headers=()
for header in include/*.h; do headers+=("include/connman/${header##*/}"); done
make -j8 "${headers[@]}" include/connman/gdbus.h src/builtin.h
make -j8 CPPFLAGS="-I$WORK/headers" unit/test-service src/connmand
mkdir -p "$WORK/package"
cp src/connmand COPYING "$WORK/package/"
cp "$REPO/connman-patches/90-sailplay-lifecycle.conf" "$WORK/package/"
rpmbuild -bb --target aarch64 --define 'debug_package %{nil}' \
    --define '__os_install_post %{nil}' --define "_sourcedir $WORK/package" \
    "$REPO/connman-patches/sailplay-connman-fix.spec"
