"""The applet's timelogic.js against the Qt tray's timelogic.py.

Both front ends word the Time section themselves, one in JavaScript for
Plasma and one in Python for every other desktop. This runs the JavaScript
under node over every fake helper output in time_fixtures and requires the
same answer, word for word, as the Python. It also runs the applet's
dispatch, sourceKind(), whose order (" time state" before " state") decides
whether a time poll is read as the device list.

Skips with the reason when node is not installed, unless
HAMMUNITION_REQUIRE_NODE=1 is set -- which CI sets, so a missing node there
is a failure rather than a skip that passes forever.
"""

import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qt"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hammunition_tray_qt import timelogic  # noqa: E402
from time_fixtures import POLLS, STATES  # noqa: E402

JS = ROOT / "plasmoid/package/contents/ui/timelogic.js"
MAIN = ROOT / "plasmoid/package/contents/ui/main.qml"
HELPER = "/usr/local/libexec/hammunition-devctl"

NODE = shutil.which("node")
if NODE is None and os.environ.get("HAMMUNITION_REQUIRE_NODE") == "1":
    raise RuntimeError("node is not installed, and HAMMUNITION_REQUIRE_NODE=1")

# Loads the library script the way QML does, minus its pragma, and answers
# every case on stdin. tr() stands in for i18n: %1, %2 replaced, nothing else.
HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8").replace(/^\.pragma library\s*$/m, "");
const L = {};
vm.createContext(L);
vm.runInContext(src, L, { filename: process.argv[1] });
const tr = (m, ...a) => m.replace(/%(\d)/g, (_, n) => String(a[Number(n) - 1]));
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = { modes: Array.from(L.MODES), floor: L.ENGINE_FLOOR, states: {}, polls: {}, kinds: {} };
out.labels = L.MODES.concat(["gps-pps"]).map(m => L.modeLabel(m, tr));
out.unsupported = L.headline(null, true, tr);
out.reading = L.headline(null, false, tr);
out.nullNotes = L.notes(null, tr);
out.nullGreyed = L.greyed(null);
out.nullRtc = L.rtcNote(null, tr);
for (const [name, row] of Object.entries(input.states)) {
  const t = L.parseTimeState(JSON.stringify(row));
  out.states[name] = {
    parsed: t,
    headline: L.headline(t, false, tr),
    notes: L.notes(t, tr),
    greyed: L.greyed(t),
    canChoose: L.canChoose(t, false),
    canChooseUnsupported: L.canChoose(t, true),
    rtc: L.rtcNote(t, tr),
  };
}
for (const [name, [code, stdout, stderr]] of Object.entries(input.polls)) {
  out.polls[name] = L.pollOutcome(code, stdout, stderr, tr);
}
for (const source of input.sources) out.kinds[source] = L.sourceKind(source);
process.stdout.write(JSON.stringify(out));
"""

SOURCES = {
    f"{HELPER} state": "devices",
    f"{HELPER} time state": "time",
    f"/usr/bin/pkexec {HELPER} park gps-receiver@1-4": "action",
    f"/usr/bin/pkexec {HELPER} wake gps-receiver@1-4": "action",
    f"/usr/bin/pkexec {HELPER} time mode gps-only": "action",
}


def as_js(state):
    if state is None:
        return None
    d = dataclasses.asdict(state)
    d["problems"] = list(d["problems"])
    return d


@unittest.skipIf(NODE is None, "node is not installed; install nodejs to run this")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.dumps({"states": STATES, "polls": POLLS, "sources": list(SOURCES)})
        p = subprocess.run(
            [NODE, "-e", HARNESS, str(JS)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if p.returncode != 0:
            raise AssertionError(f"timelogic.js failed under node:\n{p.stderr}")
        cls.js = json.loads(p.stdout)

    def test_the_modes_and_the_floor(self):
        self.assertEqual(self.js["modes"], list(timelogic.MODES))
        self.assertEqual(self.js["floor"], timelogic.ENGINE_FLOOR)

    def test_main_qml_offers_the_same_four_modes(self):
        found = re.search(r"readonly property var timeModes: \[([^\]]*)\]", MAIN.read_text())
        self.assertIsNotNone(found, "main.qml's timeModes is gone")
        self.assertEqual(re.findall(r'"([^"]+)"', found.group(1)), list(timelogic.MODES))

    def test_the_mode_labels(self):
        self.assertEqual(
            self.js["labels"], [timelogic.mode_label(m) for m in (*timelogic.MODES, "gps-pps")]
        )

    def test_before_a_state_exists(self):
        self.assertEqual(self.js["unsupported"], timelogic.headline(None, True))
        self.assertEqual(self.js["reading"], timelogic.headline(None, False))
        self.assertEqual(self.js["nullNotes"], timelogic.notes(None))
        self.assertEqual(self.js["nullGreyed"], timelogic.greyed(None))
        self.assertEqual(self.js["nullRtc"], timelogic.rtc_note(None))

    def test_every_state_reads_the_same(self):
        for name, row in STATES.items():
            with self.subTest(name):
                t = timelogic.parse_time_state(json.dumps(row))
                js = self.js["states"][name]
                self.assertEqual(js["parsed"], as_js(t))
                self.assertEqual(js["headline"], timelogic.headline(t, False))
                self.assertEqual(js["notes"], timelogic.notes(t))
                self.assertEqual(js["greyed"], timelogic.greyed(t))
                self.assertEqual(js["canChoose"], timelogic.can_choose(t, False))
                self.assertEqual(js["canChooseUnsupported"], timelogic.can_choose(t, True))
                self.assertEqual(js["rtc"], timelogic.rtc_note(t))

    def test_every_poll_means_the_same(self):
        for name, (code, stdout, stderr) in POLLS.items():
            with self.subTest(name):
                py = timelogic.poll_outcome(True, False, code, stdout, stderr)
                js = self.js["polls"][name]
                self.assertEqual(js["state"], as_js(py.state))
                self.assertEqual(js["unsupported"], py.unsupported)
                self.assertEqual(js["error"], py.error)
                self.assertEqual(js["keep"], py.keep)

    def test_the_old_engine_is_unsupported_in_both(self):
        self.assertTrue(self.js["polls"]["old-engine"]["unsupported"])
        self.assertEqual(self.js["polls"]["old-engine"]["error"], "")

    def test_time_state_is_dispatched_before_device_state(self):
        # " time state" contains " state". Tested second, a time poll would
        # be parsed as the device list and fail as "Could not parse".
        self.assertEqual(self.js["kinds"], SOURCES)

    def test_main_qml_dispatches_through_source_kind(self):
        main = MAIN.read_text()
        self.assertIn("TimeLogic.sourceKind(source)", main)
        self.assertNotIn('source.indexOf(" state")', main)


if __name__ == "__main__":
    unittest.main()
