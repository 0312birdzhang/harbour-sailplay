# ConnMan service lifetime fix

This is a separate system networking fix, not a change to CarPlay credentials or
an instruction to ignore `NoCarrier`. It targets the retained-service-object
defect reproduced with Sailfish ConnMan `1.40+git26.6`.

## Upstream review on 2026-11-13

PR #166 was closed. The maintainer explained that retaining services after
network removal is intentional in the Sailfish Wi-Fi architecture.
[Review comment](https://github.com/sailfishos/connman/pull/166#issuecomment-6849323905)

The fork has two retention paths. When a saved Wi-Fi network disappears,
`__connman_service_remove_from_network()` clears its network pointer and keeps
the service in `service_hash`. Its public path remains registered, and a new
network with the same identifier reuses the service through
`update_from_network()`. Calling `Remove` while the network is still present
also retains the service and marks it unsaved. These paths preserve the
service's public interface with the current patch applied.
[Service implementation](https://github.com/sailfishos/connman/blob/dde68eca/connman/src/service.c#L10768)

The collision examined by this workaround occurs when an unsaved service
actually leaves the identifier table while another owner retains a reference.
Reappearance creates a second service. On unpatched source, the existing
interface still points to the detached first service, while the identifier
table points to the available replacement. `service_register()` ignores the
failed duplicate registration, and the old object's D-Bus `Connect` method
returns `NoCarrier`.
[Registration](https://github.com/sailfishos/connman/blob/dde68eca/connman/src/service.c#L9853)
[Connect method](https://github.com/sailfishos/connman/blob/dde68eca/connman/src/service.c#L6652)

The review prompted three additional tests against `1.40+git40`, commit
`dde68eca`. They use real network creation, grouping, removal and replacement
functions with the existing service harness. Saved-network disappearance and
reappearance pass on both stock and patched source. Forgetting an available
network also passes on both. Unsaved-network replacement with an outstanding
reference reproduces the old/new interface mismatch and `NoCarrier` on stock
source. The patched source passes all 17 service tests. The AArch64 SDK run and
the session-user run on `192.168.3.234` produce the same results.

The refreshed patch and all 17 service tests are published on
`0312birdzhang/connman`, branch `fix-service-registry-lifetime-git40`, at commit
`b8b10a6b3efacaf4a6cc67a0c5f5af5d95213988`.
[Published source](https://github.com/0312birdzhang/connman/tree/fix-service-registry-lifetime-git40)

These additional tests use a duplicate-rejecting D-Bus registry fixture and a
deliberately retained reference. The original PR's internal-removal test did
not cover the intentional Wi-Fi retention paths. The patch remains a locally
validated workaround with a closed upstream submission. Further upstream
evaluation needs a real-daemon Wi-Fi trace identifying the outstanding owner
and documenting the intended interface lifecycle for this collision. Local
review evidence is retained under `.private/connman-review-20261113/`.

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
`sailplay-connman-fix-1.0.0-3.aarch64.rpm`. Set `CONNMAN_SOURCE_ROOT` to the
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

Release 3 adds the VPN symbol and AArch64 checks to the RPM's `%check` phase,
including the staged payload. Each build uses its own RPM directory and exports
the package identified by the spec. The daemon version now identifies the fix
release, for example `1.40+git26.6.sailplay3`. Source archives use a temporary
protected Git configuration, which also works with the available WSL Git 2.34.1.

## Installation and rollback

This RPM is deliberately restricted to the tested aarch64 ConnMan package
`1.40+git26.6-1.43.1.jolla` and stock daemon SHA-256
`eb2b3ea18f6ce949bf58fe6832121aaa93f6362b54e67b8d8c84f21117826421`.
Other devices or OS versions require a matching rebuild and validation.

The 2026-11-13 report identifies SailfishOS `5.2.0.22` and ConnMan
`1.40+git26.6`. Installation checks the full package release and stock daemon
identity above. The affected user's installed `sailplay-connman-fix` release
is still unknown. Release 1 contains the reproduced missing-bridge defect,
and release 2 includes its core fix.

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

Release 3 was rebuilt and checked on 2026-11-13. The final RPM is 557,789 bytes
and has SHA-256
`7bebcf6bf824ddc45476b46f8edadbe9662251bfa817f58f3629edcbd8691e48`.
Its extracted daemon and systemd override match the build outputs. All 14
service tests passed in the SDK, including `registry_retained_reference`.
Direct RPM builds rejected both the earlier bridge-free AArch64 daemon and an
x86-64 executable during `%check`.

The extracted release-3 daemon also passed a runtime check on a private D-Bus
and an isolated network namespace. A simulated vpnd supplied OpenConnect,
OpenVPN, VPNC, L2TP, PPTP, OpenFortiVPN, WireGuard, Xray and Hysteria2 providers.
All nine appeared in `GetServices`, and their listed and direct properties
agreed. Failure and idle transitions, connection removal, recreation of the
same path, disappearance of vpnd and its return with a different D-Bus owner
passed while the main ConnMan owner stayed the same. A fabricated association
without an underlying transport reached vpnd's `Disconnect` method and returned
to idle. The earlier bridge-free daemon exposed zero VPN services against the
same simulated providers.

The available cross-build target reports OS metadata `5.1.0.11` and currently
contains glibc `2.41+git5` and libgsupplicant `1.0.30`. The build uses the pinned
libgsupplicant `1.0.31` headers described above. All 755 external dynamic symbol
dependencies match the retained release-2 daemon, including its GLIBC symbol
version requirements through `2.38`. The initial accessible phone ran
SailfishOS `5.3.0.15`, ConnMan `1.40+git36` and the stock daemon.

### SailfishOS 5.2.0.22 device verification on 2026-11-13

The authorized test device at `192.168.3.234` runs SailfishOS `5.2.0.22` and
ConnMan `1.40+git26.6-1.43.1.jolla`. Its stock daemon matched the installation
hash gate. Release 3 was installed with an independently tested rollback timer,
and the running executable reported `1.40+git26.6.sailplay3`. All 14 service
tests passed as the session user. Both main ConnMan and vpnd listed 31 VPN
configurations.

Three successful release-3 Xray VMess/WebSocket connections carried real HTTPS
traffic through `utun50`. Each successful run returned HTTP 200 for both the
normal request and a request explicitly bound to the tunnel. Route lookup used
the tunnel and its receive/transmit counters increased. Main ConnMan's process
and D-Bus owner remained unchanged throughout the resumed tests. The second
and third successes used the same vpnd process and owner. VPN properties
matched between listed and direct calls, and the configuration keys were
preserved. The earlier stock-daemon run also carried real tunnel traffic.

The three successes were interspersed with failures, so consecutive-reconnect
acceptance remains open. The retained early log reported an unreachable proxy
endpoint. Resumed failure logs also showed Xray loading its configuration and
then `xray: interface utun50 did not come up (-110)`. The current Xray plugin
source waits 5000 ms for the interface. One recorded failed startup took about
5.6 seconds to reach Xray's started log, while successful startups were near
that deadline. This locates a remaining startup failure in the VPN plugin's
interface-wait path. This test does not establish the cause of its variable
startup duration. A following main-service connect returned `OperationAborted`
and cleared the failed state, and a further retry succeeded without restarting
either daemon.

The original test configuration was replaced between sessions, so the resumed
runs used an existing current configuration with reachable server ports.
Disconnect removed an existing Wi-Fi gateway host route, as also recorded in
the stock test. The diagnostic restored that exact route only when it was the
sole route difference. Routes, policy rules, interfaces and saved reverse-path
filter values were checked after teardown. Temporary logging and installation
resources are cleaned under content and identity guards. The final live device
check is recorded in `todo.md`.
