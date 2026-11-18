"""pytest plugin: record every Python-vs-browser comparison made by tests/test_offline_verifier.py.

Wraps the module-level agree() helper. For each call it stores the test id, both verdicts and both
sets of failed checks, then re-runs the original (so the test's own assertions still apply).
Output: $AGREE_OUT (JSON).
"""
import json
import os

RECORDS = []
_current = {"id": None}


def pytest_runtest_setup(item):
    _current["id"] = item.nodeid


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        mod = getattr(item, "module", None)
        if mod is None or not mod.__name__.endswith("test_offline_verifier"):
            continue
        if getattr(mod, "_agree_wrapped", False):
            continue
        orig = mod.agree

        def wrapped(app, page, bundle, pins=None, _orig=orig, _mod=mod):
            js = _mod.in_browser(page, bundle, pins)
            py = _mod.in_python(
                app,
                bundle,
                expect_log=(pins or {}).get("log"),
                expect_witness=(pins or {}).get("witness"),
            )
            js_failed = sorted(c["key"] for c in js["checks"] if not c["ok"] and not c["skipped"])
            py_failed = sorted(c.key for c in py.failures)
            RECORDS.append(
                {
                    "test": _current["id"],
                    "python_ok": bool(py.ok),
                    "browser_ok": bool(js["ok"]),
                    "python_failed": py_failed,
                    "browser_failed": js_failed,
                    "agree": bool(py.ok) == bool(js["ok"]) and py_failed == js_failed,
                }
            )
            return _orig(app, page, bundle, pins)

        mod.agree = wrapped
        mod._agree_wrapped = True


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("AGREE_OUT", "agree_records.json")
    summary = {
        "comparisons": len(RECORDS),
        "disagreements": sum(1 for r in RECORDS if not r["agree"]),
        "pytest_exitstatus": int(exitstatus),
        "records": RECORDS,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
