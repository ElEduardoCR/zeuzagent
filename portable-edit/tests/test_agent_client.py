import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from zeuzedit_desktop.agent_client import AgentClient, AgentError


class Handler(BaseHTTPRequestHandler):
    requests = []
    fail_send = False
    old_agent = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    def handle_request(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
        path = urlsplit(self.path).path
        if path == "/v1/dnc/program/send" and self.old_agent:
            payload = b'{"error":"Ruta no encontrada"}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        response = {"ok": True}
        if path == "/v1/pair":
            response = {"token": "test-token", "agent_name": "Test Agent"}
        elif path == "/v1/dnc/machines":
            response = [{"id": "fadal-id", "name": "Fadal"}]
        elif path == "/v1/programs":
            response = {"path": body["name"], "modified": 10.5}
        elif path == "/v1/programs/content":
            response = {"path": body["path"], "modified": 12}
        elif path == "/v1/dnc/transfer/status":
            response = {"status": "success", "sent_bytes": 22, "total_bytes": 22}
        elif path == "/v1/dnc/program/send" and self.fail_send:
            self.connection.close()
            return
        payload = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class AgentTests(unittest.TestCase):
    def setUp(self):
        Handler.requests, Handler.fail_send, Handler.old_agent = [], False, False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = AgentClient(f"http://127.0.0.1:{self.server.server_port}", timeout=1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_pair_upload_send_status_cancel_contract(self):
        self.assertEqual(self.client.pair("123 456"), "Test Agent")
        self.assertEqual(Handler.requests[0][3], {"code": "123456"})
        self.assertEqual(self.client.machines()[0]["id"], "fadal-id")
        path = self.client.upload("sample.nc", "G1X1\r\nM30\r\n")
        self.client.send(path, "fadal-id")
        self.client.status("fadal-id")
        self.client.cancel("fadal-id")
        for method, route, auth, body in Handler.requests[1:]:
            self.assertEqual(auth, "Bearer test-token")
        write = next(value for value in Handler.requests if value[0] == "PUT")
        self.assertEqual(write[3]["content"], "G1X1\r\nM30\r\n")
        self.assertEqual(write[3]["expected_modified"], 10.5)
        send = next(value for value in Handler.requests if value[1] == "/v1/dnc/program/send")
        self.assertEqual(send[3], {"path": path, "machine_id": "fadal-id"})
        self.assertNotEqual(path, "sample.nc")
        status = next(value for value in Handler.requests if value[1].startswith("/v1/dnc/transfer/status"))
        self.assertEqual(parse_qs(urlsplit(status[1]).query), {"machine_id": ["fadal-id"]})
        self.assertEqual(Handler.requests[-1][3], {"machine_id": "fadal-id"})

    def test_uncertain_send_is_never_retried(self):
        Handler.fail_send = True
        with self.assertRaisesRegex(AgentError, "No se confirmó"):
            self.client.send("program.nc", "fadal-id")
        self.assertEqual(len(Handler.requests), 1)

    def test_old_agent_requires_update_without_fallback(self):
        Handler.old_agent = True
        with self.assertRaisesRegex(AgentError, "Actualiza Zeuz Agent"):
            self.client.send("program.nc", "fadal-id")
        self.assertEqual(len(Handler.requests), 1)
        self.assertEqual(Handler.requests[0][1], "/v1/dnc/program/send")

    def test_upload_rejects_lossy_or_oversized_content_before_mutation(self):
        with self.assertRaises(UnicodeEncodeError):
            self.client.upload("sample.nc", "(工具)")
        with self.assertRaises(AgentError):
            self.client.upload("sample.nc", "x" * (4 * 1024 * 1024))
        self.assertEqual(Handler.requests, [])

    def test_endpoint_rejects_embedded_credentials_or_paths(self):
        for endpoint in ["http://user:pass@localhost", "file:///tmp", "http://localhost/private", "http://localhost?token=x"]:
            with self.subTest(endpoint=endpoint), self.assertRaises(AgentError):
                AgentClient(endpoint)


if __name__ == "__main__":
    unittest.main()
