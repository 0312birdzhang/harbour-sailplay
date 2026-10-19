Name: sailplay-connman-fix
Version: 1.0.0
Release: 1
Summary: ConnMan service registry lifetime fix for Sailplay
License: GPLv2
BuildArch: aarch64
Source0: connmand
Source1: 90-sailplay-lifecycle.conf
Source2: COPYING
Requires: connman = 1.40+git26.6-1.43.1.jolla
Requires(post): systemd
Requires(postun): systemd

%description
Unregister removed ConnMan service objects before their final reference is
released. Prevents a recreated head-unit hotspot from retaining a stale D-Bus
handler. The stock connmand is preserved; removing this package restores it.

%prep
%build
%install
install -Dm755 %{SOURCE0} %{buildroot}/usr/libexec/sailplay-connmand
install -Dm644 %{SOURCE1} %{buildroot}/usr/lib/systemd/system/connman.service.d/90-sailplay-lifecycle.conf
install -Dm644 %{SOURCE2} %{buildroot}/usr/share/licenses/%{name}/COPYING

%pre
expected=eb2b3ea18f6ce949bf58fe6832121aaa93f6362b54e67b8d8c84f21117826421
actual=$(sha256sum /usr/sbin/connmand | cut -d' ' -f1)
if [ "$actual" != "$expected" ]; then
    echo 'Unsupported stock connmand; refusing to override this device.' >&2
    exit 1
fi

%post
systemctl daemon-reload
systemctl --no-block try-restart connman.service || :

%postun
if [ "$1" = 0 ]; then
    systemctl daemon-reload
    systemctl --no-block try-restart connman.service || :
fi

%files
/usr/libexec/sailplay-connmand
/usr/lib/systemd/system/connman.service.d/90-sailplay-lifecycle.conf
/usr/share/licenses/%{name}/COPYING
