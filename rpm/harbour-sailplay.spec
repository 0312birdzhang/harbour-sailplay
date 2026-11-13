Name: harbour-sailplay
Version: 0.1.1
Release: 111
Summary: SailfishOS wireless CarPlay and Android Auto phone with virtual display
License: GPL-3.0-or-later
Source0: %{name}-%{version}.tar.bz2
BuildArch: aarch64
Requires: ffmpeg-tools
Requires: maliit-framework-wayland
Requires: maliit-framework-wayland-inputcontext
Requires: python3-base
Requires(pre): python3-base
Requires: python3-dbus
Requires: python3-gobject
Requires: sailfishsilica-qt5
Requires: sailfish-components-media-qt5
Requires: sailfish-components-weather-qt5
Requires: sailjail
Requires: nemo-qml-plugin-contacts-qt5
Requires: libcommhistory-qt5-declarative
Requires: voicecall-qt5
Requires: jolla-messages
Requires: nemo-qml-plugin-messages-internal-qt5
Requires: sailfish-components-telephony-qt5
Requires: voicecall-ui-jolla
AutoReq: 0
AutoProv: 0

%description
Wireless phone-role CarPlay integration with Bluetooth iAP2, ConnMan handover,
AirPlay pairing and encrypted H.264 video, including its own compositor,
Qt Quick launcher and statically linked x264 capture binary. Experimental
vehicle integration with continuous video, absolute HID touch, and encrypted playback audio.
Includes a phone-side wireless Android Auto backend with WPP bootstrap, AAP TLS,
negotiated H.264/PCM/AAC media, input and exclusive dual-protocol session ownership.
Includes SDK v1 application/session/navigation XML, Python provider and client
helpers, Qt/QML bindings and shared-backend reference applications.

%prep
%setup -q

%build

%install
mkdir -p %{buildroot}/opt/sailplay %{buildroot}/opt/sailplay/carui
cp -r carplay_proto android_auto sailplay_sdk scripts diagnostics %{buildroot}/opt/sailplay/
find %{buildroot}/opt/sailplay/sailplay_sdk -type f -exec chmod 0644 {} +
find %{buildroot}/opt/sailplay/sailplay_sdk -type d -exec chmod 0755 {} +
mkdir -p %{buildroot}/usr/share/sailplay-sdk
cp -r sdk/qt sdk/examples %{buildroot}/usr/share/sailplay-sdk/
find %{buildroot}/usr/share/sailplay-sdk -type f -exec chmod 0644 {} +
find %{buildroot}/usr/share/sailplay-sdk -type d -exec chmod 0755 {} +
install -m 0644 sdk/README.md %{buildroot}/usr/share/sailplay-sdk/README.md
install -m 0644 LICENSE %{buildroot}/usr/share/sailplay-sdk/LICENSE
install -D -m 0644 sailplay_sdk/interfaces/org.sailplay.App1.xml %{buildroot}/usr/share/dbus-1/interfaces/org.sailplay.App1.xml
install -D -m 0644 sailplay_sdk/interfaces/org.sailplay.Session1.xml %{buildroot}/usr/share/dbus-1/interfaces/org.sailplay.Session1.xml
install -D -m 0644 sailplay_sdk/interfaces/org.sailplay.Navigation1.xml %{buildroot}/usr/share/dbus-1/interfaces/org.sailplay.Navigation1.xml
install -D -m 0644 sailplay_sdk/interfaces/org.sailplay.Content1.xml %{buildroot}/usr/share/dbus-1/interfaces/org.sailplay.Content1.xml
install -m 2755 rpm/payload/imira-comp %{buildroot}/opt/sailplay/imira-comp
install -m 2755 rpm/payload/carlife-capture %{buildroot}/opt/sailplay/carlife-capture
install -m 0755 rpm/payload/carui %{buildroot}/opt/sailplay/carui/carui
mkdir -p %{buildroot}/opt/sailplay/communication
install -D -m 0755 rpm/payload/sailplay-communication %{buildroot}/usr/bin/sailplay-communication
ln %{buildroot}/usr/bin/sailplay-communication %{buildroot}/usr/bin/sailplay-phone-backend
ln %{buildroot}/usr/bin/sailplay-communication %{buildroot}/usr/bin/sailplay-messages-backend
install -m 2755 rpm/payload/sailplay-communication-launcher %{buildroot}/usr/bin/
install -m 0644 display-source/communication/*.qml %{buildroot}/opt/sailplay/communication/
for name in sailplay-phone sailplay-messages sailplay-phone-backend sailplay-messages-backend; do
    install -D -m 0644 rpm/$name.desktop %{buildroot}/usr/share/applications/$name.desktop
    install -D -m 0644 rpm/$name.profile %{buildroot}/etc/sailjail/permissions/$name.profile
done
for name in Phone Messages; do
    install -D -m 0644 rpm/org.sailplay.System.$name.service %{buildroot}/usr/share/dbus-1/services/org.sailplay.System.$name.service
done
install -m 0644 display-source/carui/main.qml %{buildroot}/opt/sailplay/carui/main.qml
install -m 0644 display-source/carui/CarPalette.qml %{buildroot}/opt/sailplay/carui/CarPalette.qml
install -m 0644 display-source/carui/WeatherCard.qml %{buildroot}/opt/sailplay/carui/WeatherCard.qml
install -m 0644 display-source/carui/NavigationCard.qml %{buildroot}/opt/sailplay/carui/NavigationCard.qml
install -m 0644 display-source/carui/MapDestinationPanel.qml %{buildroot}/opt/sailplay/carui/MapDestinationPanel.qml
install -m 0644 display-source/carui/MapBookmarkIcon.qml %{buildroot}/opt/sailplay/carui/MapBookmarkIcon.qml
install -m 0644 display-source/carui/ContentPage.qml %{buildroot}/opt/sailplay/carui/ContentPage.qml
install -m 0644 display-source/carui/MusicPlayer.qml %{buildroot}/opt/sailplay/carui/MusicPlayer.qml
install -m 0644 display-source/carui/mobile-settings.qml %{buildroot}/opt/sailplay/carui/mobile-settings.qml
install -m 0644 display-source/carui/AboutPage.qml %{buildroot}/opt/sailplay/carui/AboutPage.qml
install -m 0644 display-source/carui/AppSelectionPage.qml %{buildroot}/opt/sailplay/carui/AppSelectionPage.qml
printf '%s\n' '%{version}-%{release}' > %{buildroot}/opt/sailplay/version
mkdir -p %{buildroot}/opt/sailplay/carui/translations
install -m 0644 rpm/payload/translations/*.qm %{buildroot}/opt/sailplay/carui/translations/
install -m 0644 display-source/carui/harbour-sailplay.png %{buildroot}/opt/sailplay/carui/harbour-sailplay.png
install -D -m 0644 rpm/harbour-sailplay.desktop %{buildroot}/usr/share/applications/harbour-sailplay.desktop
install -D -m 0644 display-source/carui/harbour-sailplay.png %{buildroot}/usr/share/icons/hicolor/172x172/apps/harbour-sailplay.png
install -m 0644 display-source/carui/carui-apps.conf %{buildroot}/opt/sailplay/carui-apps.conf
touch %{buildroot}/opt/sailplay/diagnostics/display-ui
install -D -m 0644 rpm/sailplay.service %{buildroot}/usr/lib/systemd/system/sailplay.service
install -D -m 0644 rpm/sailplay-reconnect.service %{buildroot}/usr/lib/systemd/system/sailplay-reconnect.service
install -D -m 0644 rpm/sailplay-xpolicy.conf %{buildroot}/etc/pulse/xpolicy.conf.d/sailplay.conf
install -D -m 0644 rpm/50-sailplay.rules %{buildroot}/etc/polkit-1/rules.d/50-sailplay.rules

%pre
python3 - <<'PY'
import hashlib
import os
from pathlib import Path
policy = Path('/etc/pulse/xpolicy.conf.d/sailplay.conf')
previous = hashlib.sha256(policy.read_bytes()).hexdigest() if policy.exists() else ''
descriptor = os.open('/run/sailplay-audio-policy.previous-sha256',
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
with os.fdopen(descriptor, 'w') as record:
    record.write(previous)
PY

%post
systemctl daemon-reload || :
systemctl enable sailplay.service || :
su defaultuser -s /bin/sh -c 'env XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket python3 /opt/sailplay/scripts/reload-audio-policy.py' || echo 'Sailplay audio policy activation failed; see PulseAudio logs'
rm -f /run/sailplay-audio-policy.previous-sha256
systemctl try-restart sailplay.service || :

%preun
if [ "$1" = "0" ]; then systemctl stop sailplay.service || :; fi

%postun
systemctl daemon-reload || :

%files
%defattr(-,root,root,-)
%dir /opt/sailplay
/opt/sailplay/carplay_proto
/opt/sailplay/android_auto
/opt/sailplay/sailplay_sdk
/opt/sailplay/scripts
/opt/sailplay/diagnostics
/opt/sailplay/carui
/opt/sailplay/communication
/usr/bin/sailplay-communication
/usr/bin/sailplay-phone-backend
/usr/bin/sailplay-messages-backend
%attr(2755,root,privileged) /usr/bin/sailplay-communication-launcher
/opt/sailplay/carui-apps.conf
/opt/sailplay/version
%attr(2755,root,privileged) /opt/sailplay/imira-comp
%attr(2755,root,privileged) /opt/sailplay/carlife-capture
/usr/lib/systemd/system/sailplay.service
/usr/lib/systemd/system/sailplay-reconnect.service
/etc/pulse/xpolicy.conf.d/sailplay.conf
/etc/polkit-1/rules.d/50-sailplay.rules
/usr/share/applications/harbour-sailplay.desktop
/usr/share/applications/sailplay-phone*.desktop
/usr/share/applications/sailplay-messages*.desktop
/etc/sailjail/permissions/sailplay-phone*.profile
/etc/sailjail/permissions/sailplay-messages*.profile
/usr/share/dbus-1/services/org.sailplay.System.*.service
/usr/share/icons/hicolor/172x172/apps/harbour-sailplay.png
/usr/share/sailplay-sdk
/usr/share/dbus-1/interfaces/org.sailplay.App1.xml
/usr/share/dbus-1/interfaces/org.sailplay.Session1.xml
/usr/share/dbus-1/interfaces/org.sailplay.Navigation1.xml
/usr/share/dbus-1/interfaces/org.sailplay.Content1.xml
