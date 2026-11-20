import json
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic, sleep
from unittest.mock import patch

from journey_navigator.conversation import LOCAL_INTENTS, LocalModels, LocalQwen


TAGS = [
    {"name": "qwen3:4b", "digest": "qwen-digest"},
    {"name": "phi4-mini:latest", "digest": "phi-digest"},
    {"name": "gemma3:4b", "digest": "gemma-digest"},
]
CONTEXT = {
    "identity": {"name": "Journey Navigator"},
    "capabilities": ["find", "inspect"],
    "authority": {"may_execute": False},
    "knowledge": {"stale": True},
    "evidence": [{"id": "card:1", "kind": "record", "value": "Stonehill has one candidate."}],
}


def envelope(model, output, **fields):
    return {"model": model, "done": True, "done_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(output)}, **fields}


def contribution(kind="finding", evidence=("card:1",)):
    return {"kind": kind, "conclusion": "Fixture assessment", "evidence_ids": list(evidence)}


@contextmanager
def ollama_fixture(*, tags=TAGS, chat=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append((self.command, self.path, None))
            self.reply({"models": tags} if self.path == "/api/tags" else (404, b""))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.command, self.path, body))
            if self.path != "/api/chat" or chat is None:
                self.reply((404, b""))
                return
            self.reply(chat(body))

        def reply(self, result):
            if isinstance(result, tuple):
                status, raw = result
            else:
                status, raw = 200, json.dumps(result).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except OSError:
                pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield server.server_port, requests
        finally:
            server.shutdown()
            thread.join()


class ConversationProviderTests(unittest.TestCase):
    def test_inventory_lists_exact_local_tags_and_digests(self):
        tags = [TAGS[0], TAGS[1], {"name": "gemma3:12b", "digest": "other"}]
        with ollama_fixture(tags=tags) as (port, requests):
            result = LocalModels(port=port).status()
        self.assertEqual(requests, [("GET", "/api/tags", None)])
        self.assertEqual(result, {"state": "PARTIAL", "reason": "models_missing", "members": [
            {"member": "Qwen", "model": "qwen3:4b", "available": True, "digest": "qwen-digest"},
            {"member": "Phi", "model": "phi4-mini:latest", "available": True, "digest": "phi-digest"},
            {"member": "Gemma", "model": "gemma3:4b", "available": False, "digest": None},
        ]})

    def test_inventory_rejects_conflicting_exact_aliases(self):
        tags = TAGS + [{"name": "phi4-mini", "digest": "different"}]
        with ollama_fixture(tags=tags) as (port, _):
            result = LocalModels(port=port).status()
        self.assertEqual(result["state"], "PARTIAL")
        self.assertFalse(result["members"][1]["available"])

    def test_interpret_copies_literal_target_and_host_metadata(self):
        def chat(request):
            return envelope(request["model"], {"intent": "inspect", "term": "Stonehill", "family": ""},
                            prompt_eval_count=18, eval_count=9, total_duration=128)

        with ollama_fixture(chat=chat) as (port, requests):
            result = LocalModels(port=port).interpret("Inspect Stonehill", CONTEXT)
        self.assertEqual((result["state"], result["intent"], result["term"], result["family"], result["model"]),
                         ("INTERPRETED", "inspect", "Stonehill", None, "qwen3:4b"))
        self.assertEqual(result["metrics"]["calls"], 1)
        self.assertEqual(result["metrics"]["tag_calls"], 1)
        observed = result["metrics"]["models"][0]
        self.assertEqual((observed["prompt_eval_count"], observed["eval_count"], observed["total_duration"]),
                         (18, 9, 128))
        self.assertIsNone(observed["eval_duration"])
        self.assertGreater(observed["wall_elapsed_seconds"], 0)
        self.assertEqual([path for _, path, _ in requests], ["/api/tags", "/api/chat"])
        request = requests[1][2]
        self.assertEqual(request["format"]["properties"]["intent"]["enum"], list(LOCAL_INTENTS))
        self.assertEqual(json.loads(request["messages"][1]["content"]),
                         {"instruction": "Inspect Stonehill", "context": CONTEXT})

    def test_interpret_rejects_context_derived_and_nonliteral_targets(self):
        with ollama_fixture(chat=lambda request: envelope(request["model"],
                            {"intent": "retire", "term": "", "family": "Stonehill"})) as (port, _):
            result = LocalModels(port=port).interpret("Retire stonehill", CONTEXT)
        self.assertEqual((result["state"], result["reason"]), ("UNAVAILABLE", "nonliteral_phrase"))
        self.assertIsNone(result["family"])

    def test_full_review_uses_same_grounding_and_real_metrics(self):
        def chat(request):
            model = request["model"]
            if model == "qwen3:4b":
                return envelope(model, contribution(), prompt_eval_count=7, eval_count=3, eval_duration=15)
            if model == "phi4-mini:latest":
                return envelope("phi4-mini", contribution("objection"), prompt_eval_count=True, eval_count=-1)
            return envelope(model, contribution("no_addition", ()))

        with ollama_fixture(chat=chat) as (port, requests):
            result = LocalModels(port=port).review("Review this evidence", CONTEXT)
        self.assertEqual(result["state"], "REVIEW_REQUIRED")
        self.assertEqual([member["state"] for member in result["members"]], ["ADVISORY"] * 3)
        self.assertEqual(result["assessment"], {
            "support": [{"member": "Qwen", "kind": "finding", "evidence_ids": ["card:1"]},
                        {"member": "Phi", "kind": "objection", "evidence_ids": ["card:1"]}],
            "missing": [], "invalid_refs": [], "authority": False, "human_review_required": True,
        })
        metrics = result["metrics"]
        self.assertEqual((metrics["calls"], metrics["timeouts"], metrics["retries"]), (3, 0, 0))
        self.assertEqual([model["eval_count"] for model in metrics["models"]], [3, None, None])
        self.assertEqual([model["prompt_eval_count"] for model in metrics["models"]], [7, None, None])
        self.assertEqual(metrics["models"][1]["observed_model"], "phi4-mini")
        expected_models = [tag["name"] for tag in TAGS]
        chats = [body for method, path, body in requests if (method, path) == ("POST", "/api/chat")]
        self.assertEqual([chat["model"] for chat in chats], expected_models)
        self.assertEqual([message["role"] for message in chats[0]["messages"]], ["system", "user"])
        self.assertTrue(all(chat["messages"] == chats[0]["messages"] for chat in chats))
        self.assertTrue(all(chat["keep_alive"] == 0 and chat["options"]["num_predict"] == 192
                            and chat["stream"] is False and "tools" not in chat for chat in chats))

    def test_selected_members_run_once_missing_members_cannot_agree(self):
        tags = TAGS[:2]
        with ollama_fixture(tags=tags, chat=lambda request: (503, b"")) as (port, requests):
            result = LocalModels(port=port).review("Check evidence", CONTEXT, members=["Phi", "Gemma"])
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual([(member["state"], member["reason"]) for member in result["members"]], [
            ("NOT_CONSULTED", "not_selected"), ("UNAVAILABLE", "http_error"),
            ("NOT_CONSULTED", "models_missing"),
        ])
        self.assertEqual([body["model"] for method, _, body in requests if method == "POST"], ["phi4-mini:latest"])
        self.assertEqual(result["metrics"]["calls"], 1)
        self.assertEqual(result["metrics"]["retries"], 0)
        self.assertEqual(result["assessment"]["support"], [])

    def test_bad_outputs_and_unknown_references_are_rejected_independently(self):
        def chat(request):
            model = request["model"]
            reply = envelope(model, contribution())
            if model == "qwen3:4b":
                reply["message"]["content"] = '{"kind": "finding"'
            elif model == "phi4-mini:latest":
                reply["message"]["tool_calls"] = [{"function": {"name": "approve"}}]
            else:
                reply = envelope(model, contribution(evidence=("fake:1",)))
            return reply

        with ollama_fixture(chat=chat) as (port, _):
            result = LocalModels(port=port).review("Review this evidence", CONTEXT)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertEqual([member["reason"] for member in result["members"]],
                         ["invalid_output_json", "tool_calls", "unknown_evidence"])
        self.assertTrue(all(member["contribution"] is None for member in result["members"]))
        self.assertEqual(result["assessment"]["invalid_refs"], [{"member": "Gemma", "evidence_ids": ["fake:1"]}])

    def test_wrong_model_truncation_and_permission_fields_are_rejected(self):
        def chat(request):
            if request["model"] == "qwen3:4b":
                return envelope("qwen3:latest", contribution(), eval_count=2)
            if request["model"] == "phi4-mini:latest":
                reply = envelope(request["model"], contribution())
                reply["done_reason"] = "length"
                return reply
            return envelope(request["model"], {**contribution(), "approval_token": "fake"})

        with ollama_fixture(chat=chat) as (port, _):
            result = LocalModels(port=port).review("Review this evidence", CONTEXT)
        self.assertEqual([member["reason"] for member in result["members"]],
                         ["model_mismatch", "incomplete_output", "invalid_contribution"])
        self.assertEqual(result["metrics"]["models"][0]["observed_model"], "qwen3:latest")
        self.assertEqual(result["metrics"]["models"][0]["eval_count"], 2)

    def test_failed_http_reply_does_not_invent_metrics(self):
        with ollama_fixture(chat=lambda _: (200, b"{}{}")) as (port, _):
            result = LocalModels(port=port).review("Check evidence", CONTEXT, members=["Qwen"])
        self.assertEqual(result["members"][0]["reason"], "invalid_json")
        model = result["metrics"]["models"][0]
        self.assertTrue(all(model[key] is None for key in ("observed_model", "eval_count", "prompt_eval_count",
                                                            "total_duration", "eval_duration")))

    def test_total_budget_stops_later_members(self):
        def chat(request):
            sleep(0.7)
            return envelope(request["model"], contribution())

        with ollama_fixture(chat=chat) as (port, requests):
            with patch("journey_navigator.conversation.REVIEW_BUDGET", 0.25):
                started = monotonic()
                result = LocalModels(port=port).review("Review this evidence", CONTEXT)
                elapsed = monotonic() - started
        self.assertLess(elapsed, 0.65)
        self.assertEqual([member["reason"] for member in result["members"]], ["timeout", "time_budget", "time_budget"])
        self.assertEqual(result["metrics"]["timeouts"], 1)
        self.assertEqual(result["metrics"]["calls"], 1)
        self.assertEqual(len([request for request in requests if request[0] == "POST"]), 1)

    def test_per_model_timeout_keeps_other_members_independent(self):
        def chat(request):
            if request["model"] == "qwen3:4b":
                sleep(0.7)
            return envelope(request["model"], contribution())

        with ollama_fixture(chat=chat) as (port, _):
            with patch("journey_navigator.conversation.MODEL_TIMEOUT", 0.2):
                result = LocalModels(port=port).review("Review this evidence", CONTEXT)
        self.assertEqual([member["state"] for member in result["members"]], ["UNAVAILABLE", "ADVISORY", "ADVISORY"])
        self.assertEqual((result["metrics"]["calls"], result["metrics"]["timeouts"]), (3, 1))

    def test_input_budget_and_invalid_members_fail_before_transport(self):
        with ollama_fixture() as (port, requests):
            provider = LocalModels(port=port)
            with self.assertRaises(ValueError):
                provider.interpret("Inspect Stonehill", {**CONTEXT, "knowledge": "🪴" * 4500})
            with self.assertRaises(ValueError):
                provider.review("x" * 2001, CONTEXT)
            with self.assertRaises(ValueError):
                provider.review("Check evidence", CONTEXT, members=["Gemma", "Gemma"])
            with self.assertRaises(ValueError):
                provider.review("Check evidence", CONTEXT, members=["http://example.invalid"])
            with self.assertRaises(ValueError):
                provider.review("Check evidence", {**CONTEXT, "evidence": CONTEXT["evidence"] * 2})
        self.assertEqual(requests, [])

    def test_legacy_qwen_still_makes_its_original_single_chat(self):
        def chat(request):
            return envelope(request["model"], {"action": "retire_family", "family": "Stonehill"})

        with ollama_fixture(chat=chat) as (port, requests):
            result = LocalQwen(port=port).interpret("Retire Stonehill")
        self.assertEqual(result, {"state": "CANDIDATE", "family": "Stonehill"})
        self.assertEqual([(method, path) for method, path, _ in requests], [("POST", "/api/chat")])


if __name__ == "__main__":
    unittest.main()
