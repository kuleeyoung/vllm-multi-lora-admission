"""Exercise the actual CLI against a local HTTP fixture, with no GPU claims."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"text":"fixture output"}]}\n\n')
        if body["model"] != "broken":
            self.wfile.write(b'data: [DONE]\n\n')


class SmokeCLITests(unittest.TestCase):
    def run_fixture(self, model):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "streams.jsonl"
                p = subprocess.run([sys.executable, "-m", "bench.smoke", "--base-url",
                    f"http://127.0.0.1:{server.server_port}/v1", "--base-model", model,
                    "--output", str(output)], capture_output=True, text=True, timeout=20,
                    cwd=Path(__file__).resolve().parents[1])
                rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
                return p, rows
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_nine_streams_and_distinct_ids(self):
        p, rows = self.run_fixture("base")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({r["request_id"] for r in rows}), 9)
        self.assertEqual([r["requested_model"] for r in rows[:5]], ["base", "A", "B", "C", "D"])
        self.assertTrue(all(r["status"] == "ok" for r in rows))
        self.assertTrue(all(not r["adapter_binding_verified"] for r in rows))

    def test_one_truncated_stream_fails_cli_and_preserves_rows(self):
        p, rows = self.run_fixture("broken")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(rows), 9)
        self.assertEqual(sum(r["status"] == "error" for r in rows), 1)
