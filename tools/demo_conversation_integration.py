"""Exercise the Journey conversation routes with disposable data and model fixtures.

Run with python -m tools.demo_conversation_integration [--output /path/to/new.json].
"""

import argparse
from contextlib import closing, contextmanager
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from journey_navigator.__main__ import Navigator
from journey_navigator.history import key_for
from journey_navigator.workbench import Workbench
from tools.demo_carebloom_collection import make_demo


HISTORY_QUERY = "Search history for CareRail."
ADVICE_QUERY = 'Ask Phi about "CareRail".'
ASSET = "Moonstone Character Sheet.png"
PANEL_MESSAGE = key_for(["user", "fixture-panel"])
LEGACY_FIND_BASELINE = {
    "revision": "1fe269f",
    "route": "goal-plan",
    "instruction": "Find Moonstone",
    "use_model": True,
    "provider": "FIXTURE_ONLY",
    "interpreter_calls": 1,
}
MODEL_IDS = {"Qwen": "qwen3:4b", "Phi": "phi4-mini", "Gemma": "gemma3:4b"}


class FakeModels:
    """Deterministic replies and a gate for exercising in-flight scope changes."""

    def __init__(self):
        self.calls = []
        self.sends = []
        self.intent = "find"
        self.term = "Moonstone"
        self.family = None
        self.entered = Event()
        self.release = Event()
        self.blocked = False

    def _record(self, kind, prompt, context, members):
        self.calls.append({"kind": kind, "prompt": prompt, "context": context, "members": members})

    def _send(self, kind, member, before_send):
        if before_send is not None and not before_send():
            return False
        self.sends.append((kind, member))
        if self.blocked:
            self.entered.set()
            if not self.release.wait(10):
                raise AssertionError("Timed out waiting for the fixture inference gate")
        return True

    @staticmethod
    def _metrics(members):
        return {"calls": len(members), "retries": 0, "timeouts": 0, "prompt_eval_count": None,
                "eval_count": None, "models": [{"observed_model": MODEL_IDS[name]} for name in members]}

    def interpret(self, prompt, context, *, before_send=None):
        self._record("interpret", prompt, context, ("Qwen",))
        if not self._send("interpret", "Qwen", before_send):
            return {"state": "UNAVAILABLE", "reason": "stale_context", "metrics": self._metrics(())}
        return {"state": "INTERPRETED", "intent": self.intent, "term": self.term, "family": self.family,
                "model": MODEL_IDS["Qwen"], "metrics": self._metrics(("Qwen",))}

    def review(self, prompt, context, *, members=None, before_send=None):
        selected = tuple(members) if members is not None else tuple(MODEL_IDS)
        self._record("review", prompt, context, selected)
        sample = {"Qwen": ("finding", ["inventory"] if any(e["id"] == "inventory" for e in context["evidence"])
                          else ["knowledge"]),
                  "Phi": ("objection", ["authority"]), "Gemma": ("insufficient_evidence", [])}
        results = []
        support = []
        for name in selected:
            if not self._send("review", name, before_send):
                break
            kind, references = sample[name]
            results.append({"member": name, "model": MODEL_IDS[name], "available": True,
                            "state": "ADVISORY", "reason": None,
                            "contribution": {"kind": kind, "conclusion": f"{name} fixture advisory result.",
                                             "evidence_ids": references}})
            if references:
                support.append({"member": name, "kind": kind, "evidence_ids": references})
        consulted = [row["member"] for row in results]
        return {"state": "REVIEW_REQUIRED" if results else "UNAVAILABLE", "members": results,
                "assessment": {"authority": False, "human_review_required": True, "support": support,
                               "missing": [{"member": "Gemma", "reason": "insufficient_evidence"}]
                               if "Gemma" in consulted else [], "invalid_refs": []},
                "metrics": self._metrics(consulted)}

    def status(self):
        self._record("status", None, None, ())
        return {"state": "AVAILABLE", "reason": None,
                "members": [{"member": name, "model": model, "available": True, "digest": "fixture"}
                            for name, model in MODEL_IDS.items()]}


class ApprovalSpy:
    def __init__(self):
        self.calls = []

    def verify(self, binding, description):
        self.calls.append((binding, description))
        raise PermissionError("The disposable fixture never verifies an account.")


class LegacyInterpreterSpy:
    def __init__(self):
        self.calls = []

    def interpret(self, prompt):
        self.calls.append(prompt)
        return {"state": "NEEDS_HUMAN_DECISION", "family": None}


@contextmanager
def running_navigator(store, models, *, approver=None, interpreter=None):
    """Use the normal loopback HTTP server and an isolated Workbench store."""
    approver = approver if approver is not None else ApprovalSpy()
    interpreter = interpreter if interpreter is not None else LegacyInterpreterSpy()
    with closing(Workbench(store)) as app:
        with Navigator(app, local_models=models, approver=approver, interpreter=interpreter) as server:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .02})
            thread.start()
            try:
                yield server
            finally:
                server.shutdown()
                thread.join(5)
                check(not thread.is_alive(), "The disposable HTTP server did not stop")


def request(server, action, *, expected=200, timeout=5, session=None, origin=None, **body):
    url = server.origin + "/api/inspect/" + action
    req = Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Origin": server.origin if origin is None else origin,
        "X-Journey-Session": server.token if session is None else session,
    })
    try:
        response = urlopen(req, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        result = json.load(response)
        check(response.code == expected, f"{action}: expected HTTP {expected}, got {response.code}: {result}")
        return result


def converse(server, instruction, **body):
    return request(server, "conversation", instruction=instruction, **body)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def select(server, collection, *, retain=True):
    return request(server, "select", path=str(collection), retain=retain)["job"]


def inspect(server, job):
    steps = []
    for _ in range(30):
        result = converse(server, "Inspect the selected folder.", job=job, use_model=True)
        steps.append(result["state"])
        check(result["intent"] == "inspect" and result["metrics"]["calls"] == 0,
              "Inspect should use the existing bounded inspection without a model")
        if result["state"] == "COMPLETE":
            return result["summary"], steps
        check(result["state"] == "IN_PROGRESS", f"Unexpected inspection state: {result['state']}")
    raise AssertionError("Inspection did not complete within 30 separate HTTP steps")


def import_history(server, job, exports, pack):
    preview = request(server, "pack-preview", job=job, path=str(pack))
    request(server, "pack-apply", job=job, ticket=preview["ticket"], project="carebloomos")
    preview = request(server, "history-preview", job=job, path=str(exports))
    before = request(server, "history-status", job=job)
    check(before["files"] == [] and before["unique_messages"] == 0,
          "Preview must not import the selected history")
    request(server, "history-enqueue", job=job, ticket=preview["ticket"])
    deadline = monotonic() + 10
    while monotonic() < deadline:
        progress = request(server, "history-status", job=job)
        if len(progress["files"]) == 2 and all(row["status"] == "complete" for row in progress["files"]):
            check(progress["unique_messages"] == progress["text_index"]["indexed_messages"] == 3,
                  "Two overlapping exports must index three unique messages")
            return progress
        if any(row["status"] == "failed" for row in progress["files"]):
            break
        sleep(.02)
    raise AssertionError("The two disposable history files did not finish indexing")


def destination(server, job):
    return request(server, "destination-create", job=job, objective="Review the selected fixture",
                   why="Verify safe conversational access", success="Find an attributed source")["id"]


def snapshot(root):
    """Detect added, removed, edited, or touched source files and directories."""
    return {str(path.relative_to(root)): (sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                                         path.stat().st_mtime_ns)
            for path in (root, *sorted(root.rglob("*")))}


def run_demo():
    """Return observed fixture evidence after completing and reopening the HTTP run."""
    report = {}
    with TemporaryDirectory(prefix="journey-conversation-demo-") as temporary:
        base = Path(temporary).resolve()
        fixture = base / "Fixture"
        collection, exports, pack = make_demo(fixture)
        original = snapshot(fixture)
        store = base / "Checkpoint"
        models, approval, legacy = FakeModels(), ApprovalSpy(), LegacyInterpreterSpy()
        print("Checking runtime identity, capabilities, and permissions", flush=True)
        with running_navigator(store, models, approver=approval, interpreter=legacy) as server:
            build = request(server, "build")
            identity = converse(server, "Who are you?", use_model=True)
            capabilities = converse(server, "What can you do?", use_model=True)
            permissions = converse(server, "What permissions do you have?", use_model=True)
            runtime = identity["identity"]["runtime"]
            check(identity["identity"]["name"] == "Journey" and runtime["build"] == build["build"],
                  "Identity did not report the running Journey build")
            routes = {route["id"]: route["availability"] for route in capabilities["capabilities"]}
            check(routes["find"] == "requires_active_inspection", "Unselected Find was advertised as available")
            check(permissions["authority"]["inspection"] == "not_granted" and not models.calls,
                  "Preselection must confer no scope or spend inference")
            report["A"] = {"name": identity["identity"]["name"], "runtime": runtime}
            report["B"] = {"route_availability_before_selection": routes}
            report["C"] = {"authority_before_selection": permissions["authority"]}

            print("Inspecting collection copies and importing the approved fixture exports", flush=True)
            job = select(server, collection)
            summary, steps = inspect(server, job)
            check(summary["analyzed"] == 10, "Inspection did not analyze the ten controlled fixture assets")
            report["E"] = {"steps": steps, "analyzed": summary["analyzed"], "pending": summary["pending"],
                           "pending_folders": summary["pending_folders"]}
            found = converse(server, "Find Moonstone", job=job, use_model=True)
            titles = [row["title"] for row in found["results"]]
            check(ASSET in titles and not models.calls, "Deterministic Find failed or invoked a model")
            key = destination(server, job)
            legacy_find = request(server, "goal-plan", destination=key, instruction="Find Moonstone",
                                  use_model=True)
            check(ASSET in [row["title"] for row in legacy_find["results"]] and not legacy.calls,
                  "The current goal-plan returned different Find evidence or invoked the legacy model")
            interpreted = converse(server, "For Moonstone, could you surface the relevant sheet?", job=job,
                                   use_model=True)
            check(interpreted["intent"] == "find" and len(models.calls) == 1
                  and ASSET in [row["title"] for row in interpreted["results"]],
                  "Unrecognized phrasing did not use one interpreter call and the scoped Find route")
            report["D"] = {"deterministic_find": titles, "interpreted_route": interpreted["intent"],
                           "interpreted_metrics": interpreted["metrics"]}
            imported = import_history(server, job, exports, pack)
            history = converse(server, HISTORY_QUERY, job=job)
            check(len(history["results"]) == 1, "The shared fixture message must be deduplicated in search")
            reference = history["results"][0]
            check(reference["message"] == PANEL_MESSAGE and reference["authored"] and reference["imported"]
                  and reference["authored"] != reference["imported"], "The reference lost its source or dates")
            report["G"] = {"indexed_messages": imported["unique_messages"], "completed_exports": len(imported["files"]),
                           "reference": {k: reference[k] for k in ("message", "role", "authored", "imported", "name")},
                           "history_monitor_enabled": imported["monitor"]["enabled"]}

            print("Checking advisory consent and escalation with model fixtures", flush=True)
            no_calls = len(models.calls)
            refused = converse(server, "Ask the full Council to review the selected collection.", job=job)
            check(refused["state"] == "LOCAL_MODEL_CONSENT_REQUIRED" and len(models.calls) == no_calls,
                  "Council consultation bypassed consent")
            qwen = converse(server, "Advise on the selected collection.", job=job, use_model=True)
            phi = converse(server, ADVICE_QUERY, job=job, use_model=True, share_evidence=True)
            council = converse(server, "Ask the full Council to review the selected collection.", job=job,
                              use_model=True)
            results = (qwen, phi, council)
            received = [[row["member"] for row in result["council"]["members"]] for result in results]
            check(received == [["Qwen"], ["Phi"], list(MODEL_IDS)] and len(models.calls) == no_calls + 3,
                  "Council member attribution or escalation was incorrect")
            check(all(result["state"] == "REVIEW_REQUIRED" and result["council"]["assessment"]["authority"] is False
                      for result in results), "An advisory result claimed approval")
            shared = models.calls[-2]["context"]["evidence"]
            check(any(row["kind"] == "imported_history_excerpt" and row["value"]["message"] == PANEL_MESSAGE
                      for row in shared), "Consented advisory context omitted the bounded history reference")
            report["F"] = {"status": "FIXTURE_ONLY", "live_model_grounding": "LOCAL_RUNTIME_ACCEPTANCE_PENDING",
                           "members": council["council"]["members"], "assessment": council["council"]["assessment"],
                           "shared_reference_ids": [row["id"] for row in shared]}
            report["H"] = {"recorded_old_goal_plan_find": LEGACY_FIND_BASELINE,
                           "current_goal_plan_interpreter_calls": len(legacy.calls),
                           "direct_find_metrics": found["metrics"], "no_consent_metrics": refused["metrics"],
                           "qwen_metrics": qwen["metrics"], "phi_metrics": phi["metrics"],
                           "full_council_metrics": council["metrics"]}

            print("Verifying the mutation boundary before reopening", flush=True)
            for prompt in ("Delete Moonstone.", "Approve the batch.", "Grant unattended execution."):
                held = converse(server, prompt, job=job, destination=key, use_model=True)
                check(held["state"] == "REVIEW_REQUIRED" and held["metrics"]["calls"] == 0,
                      f"Mutation request crossed the review boundary: {prompt}")
            work = request(server, "patrol-status", destination=key)
            checked = snapshot(fixture) == original
            check(checked and not approval.calls and not work["batches"] and work["metrics"]["physical_verified"] == 0,
                  "The conversation altered source material or reached guided execution")

        with running_navigator(store, FakeModels()) as server:
            check(job in {entry["id"] for entry in request(server, "jobs")["items"]},
                  "Reopening did not recover the retained inspection")
            status = converse(server, "What do you remember?", job=job)
            after = converse(server, HISTORY_QUERY, job=job)
            check(status["knowledge"]["conversation_transcript"] == "not_saved"
                  and status["knowledge"]["history_messages"] == 3 and after["results"] == history["results"],
                  "Reopening changed the retained evidence or claimed continuity beyond the checkpoint")
            report["G"].update(reopened_checkpoint=True,
                               transcript=status["knowledge"]["conversation_transcript"])
            wrong_session = converse(server, "Find Moonstone", job=job, session="invalid-fixture-session",
                                     expected=403)
            check("results" not in wrong_session, "An invalid session retrieved the inspection")
            revoked = request(server, "revoke", job=job, scope=str(collection), permission="inspect")
            blocked = converse(server, "Find Moonstone", job=job, expected=403)
            check(revoked["closed"] and "results" not in blocked, "Revocation did not close inspection access")
        check(snapshot(fixture) == original, "The controlled source tree changed while reopening")
        report["I"] = {"source_hashes_and_mtimes_unchanged": True, "observed_source_entries": len(original),
                       "account_verification_calls": len(approval.calls), "batches": len(work["batches"]),
                       "physical_operations": work["metrics"]["physical_verified"],
                       "invalid_session_http_status": 403, "post_revocation_find_http_status": 403}
        report["J"] = {"status": "LOCAL_RUNTIME_ACCEPTANCE_PENDING",
                       "observed_surface": "Disposable authenticated Navigator loopback HTTP service"}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optionally write the JSON evidence to a new file")
    args = parser.parse_args()
    try:
        report = json.dumps(run_demo(), indent=2, ensure_ascii=False)
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(report + "\n")
        print(report)
    except Exception as error:
        print(f"FINISHED FAILED: {error}", flush=True)
        return 1
    print("FINISHED SUCCESS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
