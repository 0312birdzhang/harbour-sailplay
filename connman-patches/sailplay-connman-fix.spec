Name: sailplay-connman-fix
Version: 1.0.0
Release: 3
Summary: ConnMan service registry lifetime fix for Sailplay
License: GPLv2
BuildArch: aarch64
Source0: connmand
Source1: 90-sailplay-lifecycle.conf
Source2: COPYING
BuildRequires: binutils
Requires: connman = 1.40+git26.6-1.43.1.jolla
Requires(post): systemd
Requires(postun): systemd

%description
Unregister removed ConnMan service objects before their final reference is
released. Prevents a recreated head-unit hotspot from retaining a stale D-Bus
handler. Includes the main daemon's VPN bridge for existing VPN providers.

%prep
%build
%install
install -Dm755 %{SOURCE0} %{buildroot}/usr/libexec/sailplay-connmand
install -Dm644 %{SOURCE1} %{buildroot}/usr/lib/systemd/system/connman.service.d/90-sailplay-lifecycle.conf
install -Dm644 %{SOURCE2} %{buildroot}/usr/share/licenses/%{name}/COPYING

%check
daemon=%{buildroot}/usr/libexec/sailplay-connmand
if ! LC_ALL=C readelf -h "$daemon" | grep -E 'Machine:[[:space:]]+AArch64' > /dev/null; then
    echo 'Replacement connmand must be an AArch64 ELF executable.' >&2
    exit 1
fi
if ! LC_ALL=C nm --defined-only "$daemon" | grep -E '[[:space:]]__connman_builtin_vpn$' > /dev/null; then
    echo 'Replacement connmand must include the built-in VPN bridge.' >&2
    exit 1
fi

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
