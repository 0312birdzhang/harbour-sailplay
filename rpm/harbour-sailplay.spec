Name: harbour-sailplay
Version: 0.1.0
Release: 33
Summary: SailfishOS wireless CarPlay phone and virtual vehicle display
License: GPL-3.0-or-later
Source0: %{name}-%{version}.tar.bz2
BuildArch: aarch64
Requires: python3-base
Requires: python3-dbus
Requires: python3-gobject
Requires: sailfishsilica-qt5
AutoReq: 0
AutoProv: 0

%description
Wireless phone-role CarPlay integration with Bluetooth iAP2, ConnMan handover,
AirPlay pairing and encrypted H.264 video, including its own compositor,
Qt Quick launcher and statically linked x264 capture binary. Experimental
vehicle integration with continuous video, absolute HID touch, and encrypted playback audio.

%prep
%setup -q

%build

%install
mkdir -p %{buildroot}/opt/sailplay %{buildroot}/opt/sailplay/carui
cp -r carplay_proto scripts diagnostics %{buildroot}/opt/sailplay/
install -m 2755 rpm/payload/imira-comp %{buildroot}/opt/sailplay/imira-comp
install -m 2755 rpm/payload/carlife-capture %{buildroot}/opt/sailplay/carlife-capture
install -m 0755 rpm/payload/carui %{buildroot}/opt/sailplay/carui/carui
install -m 0644 display-source/carui/main.qml %{buildroot}/opt/sailplay/carui/main.qml
install -m 0644 display-source/carui/mobile-settings.qml %{buildroot}/opt/sailplay/carui/mobile-settings.qml
install -m 0644 display-source/carui/harbour-sailplay.png %{buildroot}/opt/sailplay/carui/harbour-sailplay.png
install -D -m 0644 rpm/harbour-sailplay.desktop %{buildroot}/usr/share/applications/harbour-sailplay.desktop
install -D -m 0644 display-source/carui/harbour-sailplay.png %{buildroot}/usr/share/icons/hicolor/172x172/apps/harbour-sailplay.png
install -m 0644 display-source/carui/carui-apps.conf %{buildroot}/opt/sailplay/carui-apps.conf
touch %{buildroot}/opt/sailplay/diagnostics/display-ui
install -D -m 0644 rpm/sailplay.service %{buildroot}/usr/lib/systemd/system/sailplay.service
install -D -m 0644 rpm/sailplay-reconnect.service %{buildroot}/usr/lib/systemd/system/sailplay-reconnect.service
install -D -m 0644 rpm/sailplay-xpolicy.conf %{buildroot}/etc/pulse/xpolicy.conf.d/sailplay.conf
install -D -m 0644 rpm/50-sailplay.rules %{buildroot}/etc/polkit-1/rules.d/50-sailplay.rules

%post
systemctl daemon-reload || :
systemctl enable sailplay.service || :
su defaultuser -s /bin/sh -c 'env XDG_RUNTIME_DIR=/run/user/100000 python3 /opt/sailplay/scripts/reload-audio-policy.py' || echo 'Sailplay audio policy activation failed; see PulseAudio logs'
systemctl try-restart sailplay.service || :

%preun
if [ "$1" = "0" ]; then systemctl stop sailplay.service || :; fi

%postun
systemctl daemon-reload || :

%files
%defattr(-,root,root,-)
%dir /opt/sailplay
/opt/sailplay/carplay_proto
/opt/sailplay/scripts
/opt/sailplay/diagnostics
/opt/sailplay/carui
/opt/sailplay/carui-apps.conf
%attr(2755,root,privileged) /opt/sailplay/imira-comp
%attr(2755,root,privileged) /opt/sailplay/carlife-capture
/usr/lib/systemd/system/sailplay.service
/usr/lib/systemd/system/sailplay-reconnect.service
/etc/pulse/xpolicy.conf.d/sailplay.conf
/etc/polkit-1/rules.d/50-sailplay.rules
/usr/share/applications/harbour-sailplay.desktop
/usr/share/icons/hicolor/172x172/apps/harbour-sailplay.png
