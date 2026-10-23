# ConnMan service lifetime fix

This is a separate system networking fix, not a change to CarPlay credentials or
an instruction to ignore `NoCarrier`. It targets the retained-service-object
defect reproduced with Sailfish ConnMan `1.40+git26.6`.

## Reproduced defect

`service_remove()` removes a service from the list and identifier hash.
The hash destructor `service_removed()` drops its reference, but the D-Bus
interface remains registered until `service_free()` runs. An asynchronous
operation can keep that removed object alive. A new network with the same
identifier then appears in `GetServices`, while duplicate D-Bus registration
fails and direct calls still address the detached old object. Its `Connect`
returns `NoCarrier` before attempting association. Moving unregistration earlier also requires clearing the old path: otherwise
the delayed finalizer would unregister the replacement.

The patch unpublishes the path when the service leaves the registry. Final
destruction uses the same idempotent helper. Delayed references remain valid,
but can neither occupy nor unregister the replacement's public interface.

## Source and build

The patch is based on SailfishOS ConnMan commit
`fbb2e64b0e996c3102015a7d84098a9691f14bf7` (the `connman/` tree in the
[upstream repository](https://github.com/sailfishos/connman)).
Header compatibility uses official
[libgsupplicant 1.0.31](https://github.com/sailfishos/libgsupplicant/tree/1.0.31),
commit `f6aad2e53b3149bd332f024790ea638f2e0a7c12`, matching the tested phone's
runtime. The headers supplied by the available SDK were only 1.0.30.

`scripts/build-connman-fix-from-wsl.sh` archives those exact local source
commits, applies the patch, cross-builds the daemon and C tests, and creates
`sailplay-connman-fix-1.0.0-2.aarch64.rpm`. Set `CONNMAN_SOURCE_ROOT` to the
outer ConnMan repository, `GSUPPLICANT_SOURCE` to a clone containing the header
commit, and optionally `SAILPLAY_SDK`. The default paths match this workspace.
Run the script as WSL root, as with the normal Sailplay build helper.

The SDK needs the development packages providing libglibutil, libdbusaccess,
libgsupplicant, libmce-glib, libgofono, libgofonoext, libdbuslogserver-dbus,
libiphb, libsystemd, libiptc, libnl-3.0, libnl-genl-3.0, xtables and usb-moded.
Wi-Fi, Bluetooth, DNS backend and Sailfish network plugins use the original
package configuration. Optional VPN client executables are not rebuilt or
installed; the existing VPN daemon and plugins are untouched.

Release 2 restores the main daemon's built-in `plugins/vpn.c` bridge to
`connman-vpnd`. In this source revision the `VPN` build condition requires at
least one protocol option, so the build enables OpenVPN with an explicit target
binary path. Only `src/connmand` and the service unit test are built; no OpenVPN
executable, VPN daemon or protocol plugin is packaged. `sailfish-vpn-access`
alone does not enable this bridge. The build now checks both the generated
built-in plugin table and the daemon's `__connman_builtin_vpn` symbol before
packaging, preventing a successful build that silently omits VPN discovery.

## Installation and rollback

This RPM is deliberately restricted to the tested aarch64 ConnMan package
`1.40+git26.6-1.43.1.jolla` and stock daemon SHA-256
`eb2b3ea18f6ce949bf58fe6832121aaa93f6362b54e67b8d8c84f21117826421`.
Other devices or OS versions require a matching rebuild and validation.

The package installs `/usr/libexec/sailplay-connmand` and a systemd override;
it does not overwrite `/usr/sbin/connmand` or rewrite saved Wi-Fi profiles.
Removing `sailplay-connman-fix` removes the override and restarts the stock
daemon. Remove or rebuild this version-specific package before an OS ConnMan
upgrade. The normal Sailplay RPM does not automatically install this package.

For the first live installation, an independent 180-second systemd rollback
timer was armed before changing the service. It was cancelled only after the
new executable, Wi-Fi and sustained screen feedback were confirmed.

## Validation

The new `registry_retained_reference` test executes the real `src/service.c`
with the existing unit harness, augmented with a duplicate-rejecting interface
registry. It retains an old service across removal, recreates the same path,
then finalizes the old object and checks the new registration is preserved.
The unpatched source failed the removal assertion (exit 134) on the phone.
The patched source passed all 14 service tests on the same phone. Run these
tests as the session user: existing upstream IP configuration tests attempt
sysctl operations and should not be given root privileges on a live device.

The patched daemon was installed and confirmed as the running ConnMan
executable. Wi-Fi and CarPlay video recovered; the stock daemon checksum
remained unchanged. Three consecutive real CarPlay reconnects completed with
the same ConnMan process and D-Bus owner, and matching listed/direct Wi-Fi
interfaces. A subsequent CPU-awake control completed another three reconnects
in 30.1, 38.6 and 38.5 seconds (107.2 seconds wall and monotonic total), again
without restarting ConnMan. This exposed a separate setup-suspend delay;
Sailplay 0.1.1-32 adds bounded profile/setup CPU leases independently of this
daemon patch. Actual vehicle ignition cycles still require field
validation. A fixed service lifecycle cannot prevent unrelated radio,
authentication, DHCP, or head-unit failures that share the `NoCarrier` name.

With the external diagnostic wake lease disabled, the final 0.1.1-32 package
completed another real reconnect in 36.0 seconds, including at least 300 new
video frames. ConnMan still had the same process and D-Bus owner. The Sailplay
Python regression suite passed 155 tests; phase leases have separate tokens
and a bounded, non-renewable profile window per Bluetooth link.


Release 2 was installed on the same supported phone: the main ConnMan VPN
service count increased from 0 to 53, matching the unchanged vpnd's 53
connections. Wi-Fi remained ready/online and the stock daemon checksum was
unchanged. All 14 service tests, including `registry_retained_reference`, passed
as the unprivileged session user. The RPM payload contains only the replacement
main daemon, systemd override and license. This confirms VPN discovery; actual
VPN tunnel connectivity was not exercised in this validation.
