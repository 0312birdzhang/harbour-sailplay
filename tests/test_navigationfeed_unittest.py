import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from carplay_proto.navigationfeed import NavigationFeed, validate_snapshot


def snapshot(pid=123):
    return dict(schema=1, source="organicmaps", pid=pid, startTicks="777", bootId="test-boot",
                appKey="b3JnYW5pY21hcHM=", sequence=1, heartbeatMs=20000, updatedMs=19000,
                navigation=dict(state="active", routerType=0, turn=5, exitNumber=0,
                                remainingSeconds=3661, nextDistance=200, nextDistanceUnit=0,
                                remainingDistance=12.3, remainingDistanceUnit=1,
                                currentRoad="南京路", nextRoad="右转道路", destination="终点"))


class SnapshotTests(unittest.TestCase):
    def validate(self, value):
        return validate_snapshot(value, 20000, "test-boot", "777", 123)

    def test_valid_raw_navigation(self):
        value = self.validate(snapshot())
        self.assertEqual(value["navigation"]["turn"], 5)
        self.assertEqual(value["navigation"]["remainingSeconds"], 3661)

    def test_heartbeat_cannot_keep_old_guidance_alive(self):
        value = snapshot()
        value["updatedMs"] = 9999
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_reject_reboot_pid_reuse_future_time_or_old_heartbeat(self):
        for key, bad in (("bootId", "another-boot"), ("startTicks", "778"), ("pid", 124),
                         ("schema", True), ("heartbeatMs", 16999), ("updatedMs", 20001),
                         ("sequence", True), ("appKey", "unrelated")):
            value = snapshot()
            value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(value)

    def test_reject_invalid_raw_data(self):
        for key, bad in (("turn", 17), ("routerType", 1), ("remainingSeconds", -1),
                         ("nextDistanceUnit", 4), ("nextDistance", float("nan")),
                         ("nextDistance", float("inf")), ("nextDistance", True),
                         ("currentRoad", "x\0y"), ("nextRoad", "x" * 1025)):
            value = snapshot()
            value["navigation"][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                self.validate(value)

    def test_terminal_states_do_not_retain_previous_turn(self):
        for state in ("idle", "stopped", "arrived", "unavailable"):
            value = snapshot()
            value["navigation"] = {"state": state}
            self.assertEqual(self.validate(value)["navigation"], {"state": state})


@unittest.skipUnless(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"), "Linux file semantics")
class FeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "runtime/sailplay-navigation"
        self.directory.mkdir(parents=True, mode=0o700)
        self.proc = self.root / "proc"
        (self.proc / "sys/kernel/random").mkdir(parents=True)
        (self.proc / "sys/kernel/random/boot_id").write_text("test-boot\n")
        self.feed = NavigationFeed(str(self.directory.parent), os.getuid(), str(self.proc), lambda: 20000)

    def publish(self, pid=123, value=None):
        value = copy.deepcopy(value or snapshot(pid))
        path = self.directory / ("organicmaps-%d.json" % pid)
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
        process = self.proc / str(pid)
        process.mkdir(exist_ok=True)
        (process / "stat").write_text("%d (organic maps) " % pid + " ".join(["S"] + ["0"] * 18 + ["777"]))
        (process / "exe").symlink_to("/usr/bin/organicmaps")
        return path

    def test_reader_validates_process_and_rejects_stale_after_exit(self):
        self.publish()
        self.assertIsNotNone(self.feed.poll())
        (self.proc / "123/stat").unlink()
        self.assertIsNone(self.feed.poll())

    def test_does_not_arbitrate_multiple_instances(self):
        self.publish(123)
        self.publish(124)
        self.assertIsNone(self.feed.poll())
        self.assertEqual(self.feed.reason, "ambiguous")

    def test_reject_symlink_world_readable_or_oversized_file(self):
        path = self.publish()
        data = path.read_bytes()
        path.chmod(0o644)
        self.assertIsNone(self.feed.poll())
        path.chmod(0o600)
        path.write_bytes(b"x" * 16385)
        self.assertIsNone(self.feed.poll())
        target = self.root / "target.json"
        target.write_bytes(data)
        path.unlink()
        path.symlink_to(target)
        self.assertIsNone(self.feed.poll())

    def test_reject_unsafe_directory_and_different_executable(self):
        self.publish()
        self.directory.chmod(0o755)
        self.assertIsNone(self.feed.poll())
        self.directory.chmod(0o700)
        executable = self.proc / "123/exe"
        executable.unlink()
        executable.symlink_to("/usr/bin/unrelated")
        self.assertIsNone(self.feed.poll())


if __name__ == "__main__":
    unittest.main()
