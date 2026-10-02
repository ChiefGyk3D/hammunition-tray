"""The applet's controlslogic.js against the Qt tray's controls.py.

Both front ends word the Controls panel's Services and Radios groups
themselves, one in JavaScript for Plasma and one in Python for every other
desktop. This runs the JavaScript under node over every fake helper document
in controls_fixtures and requires the same answer, word for word, as the
Python: every fixed string, every row's label, detail and switch state, every
argv (including the ones it must refuse), the optimistic overlay, and the
dispatch of a finished command (timelogic.js's sourceKind).

Skips with the reason when node is not installed, unless
HAMMUNITION_REQUIRE_NODE=1 is set -- which CI sets.
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

from controls_fixtures import RADIOS, RADIOS_POLLS, SERVICES, SERVICES_POLLS  # noqa: E402
from hammunition_tray_qt import controls  # noqa: E402

UI = ROOT / "plasmoid/package/contents/ui"
JS = UI / "controlslogic.js"
TIMEJS = UI / "timelogic.js"
HELPER = "/usr/local/libexec/hammunition-devctl"
PKEXEC = "/usr/bin/pkexec"

NODE = shutil.which("node")
if NODE is None and os.environ.get("HAMMUNITION_REQUIRE_NODE") == "1":
    raise RuntimeError("node is not installed, and HAMMUNITION_REQUIRE_NODE=1")

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const load = (file) => {
  const src = fs.readFileSync(file, "utf8").replace(/^\.pragma library\s*$/m, "");
  const L = {};
  vm.createContext(L);
  vm.runInContext(src, L, { filename: file });
  return L;
};
const L = load(process.argv[1]);
const T = load(process.argv[2]);
const tr = (m, ...a) => m.replace(/%(\d)/g, (_, n) => String(a[Number(n) - 1]));
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {
  floor: L.CONTRACT_FLOOR,
  strings: L.strings(tr),
  radioNames: Array.from(L.RADIO_NAMES),
  serviceVerbs: Array.from(L.SERVICE_VERBS),
  services: {}, radios: {}, polls: { services: {}, radios: {} },
  argv: [], pending: {}, errors: {}, kinds: {},
};
for (const [name, doc] of Object.entries(input.services)) {
  const parsed = L.parseServices(JSON.stringify(doc));
  out.services[name] = { linger: parsed.linger_state, rows: parsed.rows.map(r => ({
    row: r,
    label: L.serviceLabel(r),
    detail: L.serviceDetail(r, tr),
    runChecked: L.runChecked(r),
    runVerb: L.runVerb(r),
    runEnabled: [L.runEnabled(r, false), L.runEnabled(r, true)],
    loginChecked: L.loginChecked(r),
    loginVerb: L.loginVerb(r),
    loginEnabled: [L.loginEnabled(r, false), L.loginEnabled(r, true)],
    usesPkexec: L.usesPkexec(r),
  })) };
}
for (const [name, doc] of Object.entries(input.radios)) {
  out.radios[name] = L.parseRadios(JSON.stringify(doc)).map(r => ({
    row: r,
    label: L.radioLabel(r, tr),
    detail: L.radioDetail(r, tr),
    verb: L.radioVerb(r),
    enabled: [L.radioEnabled(r, false), L.radioEnabled(r, true)],
  }));
}
for (const kind of ["services", "radios"]) {
  for (const [name, [code, stdout, stderr]] of Object.entries(input.polls[kind])) {
    out.polls[kind][name] = L.pollOutcome(kind, code, stdout, stderr, tr);
  }
}
for (const c of input.argv) {
  try {
    const a = c.kind === "service"
      ? L.serviceArgv(c.pkexec, c.helper, c.row, c.verb)
      : L.radioArgv(c.helper, c.row, c.on);
    out.argv.push({ ok: Array.from(a) });
  } catch (e) {
    out.argv.push({ refused: true });
  }
}
for (const c of input.pending) {
  const rows = L.parseServices(JSON.stringify(c.doc)).rows;
  out.pending[c.name] = L.effectiveServices(rows, c.pending);
}
out.pendingKeys = {
  start: L.servicePending("start", "x"), stop: L.servicePending("stop", "x"),
  enable: L.servicePending("enable", "x"), disable: L.servicePending("disable", "x"),
  radioOn: L.radioPending("wwan", true), radioOff: L.radioPending("wwan", false),
};
out.sameRows = Object.fromEntries(input.sameRows.map(([name, a, b]) => [name, L.sameRows(a, b)]));
out.effectiveRadios = L.effectiveRadios(
  L.parseRadios(JSON.stringify(input.radios.on)), { "radio:wwan:enabled": false });
for (const [name, [code, stderr]] of Object.entries(input.errors)) {
  out.errors[name] = L.directError(code, stderr, tr);
}
out.fresh = {};
for (const [s, e, a] of input.fresh) out.fresh[(s === null ? "None" : s) + "/" + e + "/" + (a ? "True" : "False")] = L.pendingFresh(s, e, a);
for (const source of input.sources) out.kinds[source] = T.sourceKind(source);
process.stdout.write(JSON.stringify(out));
"""


def row(**kw):
    base = {"name": "gps-tether", "unit": "u.service", "scope": "user", "description": "d",
            "active": "active", "enabled": "enabled", "root": False}
    base.update(kw)
    return base


ARGV_CASES = (
    [{"kind": "service", "row": row(), "verb": v, "pkexec": PKEXEC, "helper": HELPER}
     for v in ("start", "stop", "enable", "disable", "state", "restart", "", "start ")]
    + [{"kind": "service", "row": row(scope="system", name="gpsd"), "verb": v, "pkexec": PKEXEC,
        "helper": HELPER} for v in ("start", "stop", "enable", "disable")]
    + [{"kind": "service", "row": row(scope="machine"), "verb": "start", "pkexec": PKEXEC, "helper": HELPER}]
    + [{"kind": "service", "row": row(name=n), "verb": "start", "pkexec": PKEXEC, "helper": HELPER}
       for n in ("", "-x", "X", "a b", "a;b", "a$(id)", "a`id`", "a\nb", "a/b", "a" * 64, "a" * 65, "gps_tether")]
    + [{"kind": "radio", "row": {"name": n, "present": True, "enabled": True, "method": "nmcli", "detail": ""},
        "on": on, "helper": HELPER}
       for n in ("wwan", "wifi", "bluetooth", "lora", "wwan;id", "WIFI", "wifi ", "")
       for on in (True, False)]
)

ERRORS = {
    "ok": (0, ""),
    "one-line": (1, "error: boom\n"),
    "first-of-many": (1, "error: boom\nTraceback...\n"),
    "leading-blank": (1, "\n  error: boom  \n"),
    "silent": (3, ""),
    "refused": (2, "error: refusing\n"),
    "crlf": (1, "\r\nerror: boom\r\n"),
    "form-feed-is-not-a-line-break-here": (1, "first\x0csecond\n"),
    "not-found": (127, "sh: 1: /usr/local/libexec/hammunition-devctl: not found\n"),
}

PENDING_CASES = [
    {"name": "stop-running", "doc": SERVICES["running"], "pending": {"service:gps-tether:active": "inactive"}},
    {"name": "disable-running", "doc": SERVICES["running"], "pending": {"service:gps-tether:enabled": "disabled"}},
    {"name": "both", "doc": SERVICES["stopped"],
     "pending": {"service:gps-tether:active": "active", "service:gps-tether:enabled": "enabled"}},
    {"name": "other-row", "doc": SERVICES["d2"], "pending": {"service:gpsd:active": "inactive"}},
    {"name": "none", "doc": SERVICES["d2"], "pending": {}},
]

SOURCES = {
    f"{HELPER} state": "devices",
    f"{HELPER} time state": "time",
    f"{HELPER} services state": "services",
    f"{HELPER} radio state": "radios",
    f"{HELPER} services stop gps-tether": "control",
    f"{HELPER} services enable gps-tether": "control",
    f"{HELPER} radio off wwan": "control",
    # A service is named by its owner: nothing in a name may change which
    # parser reads the answer. These all end in or contain " state".
    f"{HELPER} services start state": "control",
    f"{HELPER} services stop state-sync": "control",
    f"{HELPER} services enable time": "control",
    f"{HELPER} services start services": "control",
    f"{HELPER} services start radio": "control",
    f"{HELPER} services start pkexec-helper": "control",
    f"{PKEXEC} {HELPER} services start state": "action",
    f"{PKEXEC} {HELPER} services stop gpsd": "action",
    f"{PKEXEC} {HELPER} park gps-receiver@1-4": "action",
    f"{PKEXEC} {HELPER} wake gps-receiver@1-4": "action",
    f"{PKEXEC} {HELPER} time mode gps-only": "action",
}


FRESH = ((0, 0, False), (0, 1, False), (1, 1, False), (1, 1, True), (2, 1, False),
         (None, 5, False), (None, 5, True))

SAME_ROWS_CASES = (
    ("same-row-key-order", [{"name": "device", "parked": False}], [{"parked": False, "name": "device"}]),
    ("changed-parked", [{"parked": False}], [{"parked": True}]),
    ("changed-enabled", [{"enabled": True}], [{"enabled": False}]),
    ("changed-active", [{"active": "active"}], [{"active": "inactive"}]),
    ("null-vs-empty-array", None, []),
    ("nested-key-order", {"rows": [{"state": {"active": "active", "enabled": []}}]},
     {"rows": [{"state": {"enabled": [], "active": "active"}}]}),
    ("empty-values", {"rows": [], "meta": {}}, {"meta": {}, "rows": []}),
    ("nested-change", {"rows": [{"values": [None, {}]}]}, {"rows": [{"values": [None, {"x": 1}]}]}),
)


def as_js(obj):
    return json.loads(json.dumps(dataclasses.asdict(obj)))


@unittest.skipIf(NODE is None, "node is not installed; install nodejs to run this")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.dumps(
            {
                "services": SERVICES,
                "radios": RADIOS,
                "polls": {"services": SERVICES_POLLS, "radios": RADIOS_POLLS},
                "argv": ARGV_CASES,
                "pending": PENDING_CASES,
                "errors": ERRORS,
                "sources": list(SOURCES),
                "fresh": [[None if s is None else s, e, a] for s, e, a in FRESH],
                "sameRows": [list(case) for case in SAME_ROWS_CASES],
            }
        )
        p = subprocess.run(
            [NODE, "-e", HARNESS, str(JS), str(TIMEJS)],
            input=payload, capture_output=True, text=True, timeout=60,
        )
        if p.returncode != 0:
            raise AssertionError(f"controlslogic.js failed under node:\n{p.stderr}")
        cls.js = json.loads(p.stdout)

    def test_the_contract_floor_is_one_number_in_both(self):
        self.assertEqual(self.js["floor"], controls.CONTRACT_FLOOR)
        text = JS.read_text()
        self.assertEqual(len(re.findall(r"CONTRACT_FLOOR\s*=", text)), 1)

    def test_every_fixed_string(self):
        self.assertEqual(self.js["strings"], controls.STRINGS)
        # None of them is empty, and the one the group says is exact.
        self.assertTrue(all(controls.STRINGS.values()))
        self.assertEqual(self.js["strings"]["update"], "update hammunition-tray")

    def test_the_closed_lists(self):
        self.assertEqual(self.js["radioNames"], list(controls.RADIO_NAMES))
        self.assertEqual(self.js["serviceVerbs"], list(controls.SERVICE_VERBS))

    def test_every_services_document_reads_and_words_the_same(self):
        for name, doc in SERVICES.items():
            with self.subTest(name):
                parsed = controls.parse_services(json.dumps(doc))
                js = self.js["services"][name]
                self.assertEqual(js["linger"], parsed.linger_state)
                self.assertEqual(len(js["rows"]), len(parsed.rows))
                for js_row, r in zip(js["rows"], parsed.rows):
                    self.assertEqual(js_row["row"], as_js(r))
                    self.assertEqual(js_row["label"], controls.service_label(r))
                    self.assertEqual(js_row["detail"], controls.service_detail(r))
                    self.assertEqual(js_row["runChecked"], controls.run_checked(r))
                    self.assertEqual(js_row["runVerb"], controls.run_verb(r))
                    self.assertEqual(
                        js_row["runEnabled"], [controls.run_enabled(r, False), controls.run_enabled(r, True)]
                    )
                    self.assertEqual(js_row["loginChecked"], controls.login_checked(r))
                    self.assertEqual(js_row["loginVerb"], controls.login_verb(r))
                    self.assertEqual(
                        js_row["loginEnabled"],
                        [controls.login_enabled(r, False), controls.login_enabled(r, True)],
                    )
                    self.assertEqual(js_row["usesPkexec"], controls.uses_pkexec(r))

    def test_every_radios_document_reads_and_words_the_same(self):
        for name, doc in RADIOS.items():
            with self.subTest(name):
                rows = controls.parse_radios(json.dumps(doc))
                js = self.js["radios"][name]
                self.assertEqual(len(js), len(rows))
                for js_row, r in zip(js, rows):
                    self.assertEqual(js_row["row"], as_js(r))
                    self.assertEqual(js_row["label"], controls.radio_label(r))
                    self.assertEqual(js_row["detail"], controls.radio_detail(r))
                    self.assertEqual(js_row["verb"], controls.radio_verb(r))
                    self.assertEqual(
                        js_row["enabled"], [controls.radio_enabled(r, False), controls.radio_enabled(r, True)]
                    )

    def test_every_poll_means_the_same(self):
        for kind, polls in (("services", SERVICES_POLLS), ("radios", RADIOS_POLLS)):
            for name, (code, stdout, stderr) in polls.items():
                with self.subTest(kind=kind, poll=name):
                    py = controls.poll_outcome(kind, True, False, code, stdout, stderr)
                    js = self.js["polls"][kind][name]
                    want = None
                    if py.doc is not None:
                        want = as_js(py.doc) if kind == "services" else [as_js(r) for r in py.doc]
                    if kind == "services" and want is not None:
                        want = {"rows": want["rows"], "linger_state": want["linger_state"]}
                    self.assertEqual(js["doc"], want)
                    self.assertEqual(js["unsupported"], py.unsupported)
                    self.assertEqual(js["error"], py.error)
                    self.assertEqual(js["keep"], py.keep)

    def test_a_helper_without_the_verb_is_unsupported_in_both(self):
        for kind in ("services", "radios"):
            self.assertTrue(self.js["polls"][kind]["old-helper"]["unsupported"])
            self.assertEqual(self.js["polls"][kind]["old-helper"]["error"], "")
            self.assertTrue(self.js["polls"][kind]["version-0"]["unsupported"])

    def test_every_argv_is_the_same_or_refused_in_both(self):
        self.assertTrue(len(self.js["argv"]) == len(ARGV_CASES) > 40)
        for case, js in zip(ARGV_CASES, self.js["argv"]):
            with self.subTest(kind=case["kind"], row=case["row"], verb=case.get("verb"), on=case.get("on")):
                try:
                    if case["kind"] == "service":
                        r = controls.ServiceRow(
                            case["row"]["name"], "u", case["row"]["scope"], "d", "active", "enabled", False
                        )
                        program, args = controls.service_argv(case["pkexec"], case["helper"], r, case["verb"])
                    else:
                        r2 = controls.RadioRow(case["row"]["name"], True, True, "nmcli", "")
                        program, args = controls.radio_argv(case["helper"], r2, case["on"])
                    self.assertEqual(js, {"ok": [program, *args]})
                except ValueError:
                    self.assertEqual(js, {"refused": True})

    def test_the_optimistic_overlay_is_the_same(self):
        for case in PENDING_CASES:
            with self.subTest(case["name"]):
                rows = controls.parse_services(json.dumps(case["doc"])).rows
                pending = tuple(case["pending"].items())
                want = [as_js(r) for r in controls.effective_services(rows, pending)]
                self.assertEqual(self.js["pending"][case["name"]], want)

    def test_the_pending_keys_are_the_same(self):
        js = self.js["pendingKeys"]
        self.assertEqual(
            js,
            {
                "start": list(controls.service_pending("start", "x")),
                "stop": list(controls.service_pending("stop", "x")),
                "enable": list(controls.service_pending("enable", "x")),
                "disable": list(controls.service_pending("disable", "x")),
                "radioOn": list(controls.radio_pending("wwan", True)),
                "radioOff": list(controls.radio_pending("wwan", False)),
            },
        )
        rows = controls.parse_radios(json.dumps(RADIOS["on"]))
        want = [as_js(r) for r in controls.effective_radios(rows, (controls.radio_pending("wwan", False),))]
        self.assertEqual(self.js["effectiveRadios"], want)

    def test_the_one_line_error_of_a_direct_verb_is_the_same(self):
        for name, (code, stderr) in ERRORS.items():
            with self.subTest(name):
                self.assertEqual(self.js["errors"][name], controls.direct_error(True, False, code, stderr))

    def test_finished_commands_are_dispatched_the_same_way(self):
        # " services state" and " radio state" before " time state" and
        # " state": the order decides which parser reads which answer.
        self.assertEqual(self.js["kinds"], SOURCES)

    def test_a_poll_is_fresh_only_when_it_started_after_the_last_verb_finished(self):
        for started, epoch, acting in FRESH:
            with self.subTest(started=started, epoch=epoch, acting=acting):
                self.assertEqual(
                    self.js["fresh"][f"{started}/{epoch}/{acting}"],
                    controls.pending_fresh(started, epoch, acting),
                )

    def test_same_rows_compares_json_values_deeply_and_ignores_object_key_order(self):
        for name, _a, _b in SAME_ROWS_CASES:
            with self.subTest(name=name):
                self.assertEqual(self.js["sameRows"][name], name in {
                    "same-row-key-order", "nested-key-order", "empty-values",
                })

    def test_main_qml_dispatches_through_source_kind_still(self):
        main = (UI / "main.qml").read_text()
        self.assertIn("TimeLogic.sourceKind(source)", main)
        self.assertNotIn('source.indexOf(" state")', main)


if __name__ == "__main__":
    unittest.main()
