# DAuto wireless recovery

The patch targets DiAuto tag `v0.3.12` and contains two ordered commits. It
reinitializes Native Android Auto when its access point transport changes and
reopens a closed Bluetooth listener after a failed session. The recovery checks
`isBusy` and the handshake attempt state before restarting discovery.

Apply it to a clean `v0.3.12` checkout with `git am`.

```sh
git am /path/to/dauto-native-transport-reconnect-0.3.12.patch
```

Sailplay also recovers the verified receiver's Bluetooth link after a failed
Wi-Fi handover or projection session. These source changes are complementary
to the DAuto listener fix.

The device verification uses the existing DAuto `0.3.12` APK. A patched APK
signed with the installed application's key has yet to be built and installed.
The patch has only been committed in the local DiAuto worktree.
