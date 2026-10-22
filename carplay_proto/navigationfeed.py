"""Read opt-in projected Organic Maps snapshots, never persistent route logs."""

import base64
import json
import math
import os
import stat
import time


APP_KEYS = frozenset(base64.b64encode(name.encode()).decode()
                     for name in ("organicmaps", "harbour-organicmaps"))
STATES = frozenset(("idle", "active", "unavailable", "stopped", "arrived"))


def _int(value, minimum=0):
    return type(value) is int and value >= minimum


def validate_snapshot(value, now_ms, boot_id, start_ticks, pid):
    """Reject stale data independently of the publisher's heartbeat."""
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1:
        raise ValueError("unsupported navigation schema")
    if value.get("source") != "organicmaps" or value.get("appKey") not in APP_KEYS:
        raise ValueError("unrecognized navigation source")
    if not _int(value.get("pid"), 1) or value["pid"] != pid:
        raise ValueError("navigation PID mismatch")
    if value.get("bootId") != boot_id or value.get("startTicks") != start_ticks:
        raise ValueError("navigation process identity mismatch")
    for key, maximum_age in (("heartbeatMs", 3000), ("updatedMs", 10000)):
        timestamp = value.get(key)
        if not _int(timestamp) or not 0 <= now_ms - timestamp <= maximum_age:
            raise ValueError("stale navigation snapshot")
    if not _int(value.get("sequence"), 1):
        raise ValueError("invalid navigation sequence")
    navigation = value.get("navigation")
    if not isinstance(navigation, dict) or navigation.get("state") not in STATES:
        raise ValueError("invalid navigation state")
    if navigation["state"] == "active":
        for key in ("routerType", "turn", "exitNumber", "remainingSeconds",
                    "nextDistanceUnit", "remainingDistanceUnit"):
            if not _int(navigation.get(key)):
                raise ValueError("invalid navigation number")
        if navigation["routerType"] != 0 or navigation["turn"] > 16:
            raise ValueError("unsupported navigation mode or turn")
        for key in ("nextDistanceUnit", "remainingDistanceUnit"):
            if navigation[key] > 3:
                raise ValueError("unsupported navigation distance unit")
        for key in ("nextDistance", "remainingDistance"):
            number = navigation.get(key)
            if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
                raise ValueError("invalid navigation distance")
        for key in ("currentRoad", "nextRoad", "destination"):
            text = navigation.get(key)
            if not isinstance(text, str) or len(text) > 1024 or "\0" in text:
                raise ValueError("invalid navigation text")
    return value


class NavigationFeed:
    def __init__(self, runtime="/run/user/100000", uid=100000, proc="/proc", clock=None):
        self.directory = os.path.join(runtime, "sailplay-navigation")
        self.uid = uid
        self.proc = proc
        self.clock = clock or (lambda: time.clock_gettime(time.CLOCK_BOOTTIME) * 1000)
        self.reason = "absent"

    def poll(self):
        """Return one validated source; never arbitrate two concurrent routes."""
        self.reason = "absent"
        valid = []
        directory = None
        try:
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(directory)
            if info.st_uid != self.uid or info.st_mode & 0o077:
                self.reason = "unsafe-directory"
                return None
            names = sorted(os.listdir(directory))
            if len(names) > 32:
                self.reason = "too-many-sources"
                return None
            with open(os.path.join(self.proc, "sys/kernel/random/boot_id")) as source:
                boot_id = source.read(128).strip()
            for name in names:
                if not name.startswith("organicmaps-") or not name.endswith(".json"):
                    continue
                try:
                    pid = int(name[len("organicmaps-"):-len(".json")])
                    value = self._read(directory, name)
                    process = os.path.join(self.proc, str(pid))
                    with open(os.path.join(process, "stat")) as source:
                        data = source.read(4096)
                    start = data[data.rindex(")") + 2:].split()[19]
                    executable = os.path.basename(os.readlink(os.path.join(process, "exe")))
                    if executable not in ("organicmaps", "harbour-organicmaps"):
                        raise ValueError("invalid navigation executable")
                    if os.stat(process).st_uid != self.uid:
                        raise ValueError("invalid navigation process owner")
                    valid.append(validate_snapshot(value, int(self.clock()), boot_id, start, pid))
                except (OSError, ValueError, TypeError, IndexError, UnicodeError):
                    self.reason = "invalid-or-expired"
            if len(valid) == 1:
                self.reason = "ready"
                return valid[0]
            if valid:
                self.reason = "ambiguous"
        except (OSError, ValueError, UnicodeError):
            pass
        finally:
            if directory is not None:
                os.close(directory)
        return None

    def _read(self, directory, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid or info.st_mode & 0o077:
                raise ValueError("unsafe navigation file")
            data = source.read(16385)
            if len(data) > 16384:
                raise ValueError("oversized navigation snapshot")
        return json.loads(data.decode("utf-8"))
