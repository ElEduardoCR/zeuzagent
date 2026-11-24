import unittest
from unittest.mock import patch

from zeuzagent.clock_sync import synchronize_clock
from zeuzagent.dnc_proxy import DNCEndpoint, DNCProxyError


NOW = 1794614400
REQUEST_ID = "fb58b926-4590-4b3c-a1c4-f1b3e1ef1f10"


class ClockProxy:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def forward(self, method, path, body, endpoint, **options):
        self.calls.append((method, path, body, endpoint, options))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def state(phase="idle", utc_unix=NOW - 365 * 86400, request_id=None, **fields):
    return {"supported": True, "phase": phase, "utc_unix": utc_unix,
            "request_id": request_id, "error": "", **fields}


class ClockSyncTests(unittest.TestCase):
    def setUp(self):
        self.elapsed = 0.0
        self.endpoint = DNCEndpoint("orange.invalid", 5000)
        self.patches = [patch("zeuzagent.clock_sync.time.time", return_value=NOW),
                        patch("zeuzagent.clock_sync.time.monotonic", side_effect=lambda: self.elapsed),
                        patch("zeuzagent.clock_sync.time.sleep", side_effect=self.advance),
                        patch("zeuzagent.clock_sync.uuid.uuid4", return_value=REQUEST_ID)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def advance(self, seconds):
        self.elapsed += seconds

    def test_legacy_404_keeps_existing_update_path(self):
        proxy = ClockProxy([(404, {"ok": False, "error": "Ruta no encontrada"})])
        synchronize_clock(proxy, self.endpoint)
        self.assertEqual(len(proxy.calls), 1)
        self.assertEqual(proxy.calls[0][:2], ("GET", "/api/system/clock/status"))

    def test_matching_clock_needs_no_write(self):
        proxy = ClockProxy([(200, state(utc_unix=NOW - 60))])
        synchronize_clock(proxy, self.endpoint)
        self.assertEqual(len(proxy.calls), 1)

    def test_accepted_sync_is_polled_once_and_actual_time_confirmed(self):
        proxy = ClockProxy([(200, state()),
                            (202, state("pending", request_id=REQUEST_ID)),
                            (200, state("succeeded", NOW, REQUEST_ID))])
        synchronize_clock(proxy, self.endpoint)
        self.assertEqual([call[:2] for call in proxy.calls], [
            ("GET", "/api/system/clock/status"), ("POST", "/api/system/clock/sync"),
            ("GET", "/api/system/clock/status")])
        self.assertEqual(proxy.calls[1][2], {"utc_unix": NOW, "request_id": REQUEST_ID})
        self.assertTrue(all(call[3] == self.endpoint for call in proxy.calls))
        self.assertTrue(all(call[4]["timeout"] <= 2 and call[4]["retry_reads"] is False
                            for call in proxy.calls))

    def test_only_succeeded_result_for_this_request_can_complete(self):
        for result in [state("succeeded", NOW, "other-request"),
                       state("succeeded", NOW - 86400, REQUEST_ID),
                       state("idle", NOW, REQUEST_ID)]:
            with self.subTest(result=result):
                proxy = ClockProxy([(200, state()), (200, result)])
                with self.assertRaises(DNCProxyError):
                    synchronize_clock(proxy, self.endpoint)

    def test_failed_or_busy_sync_preserves_actionable_error(self):
        for response in [(409, {"error": "Hay un envío en curso"}),
                         (200, state("failed", request_id=REQUEST_ID, error="No se pudo guardar el reloj"))]:
            with self.subTest(response=response):
                proxy = ClockProxy([(200, state()), response])
                with self.assertRaisesRegex(DNCProxyError, response[1]["error"]):
                    synchronize_clock(proxy, self.endpoint)
                self.assertEqual(len(proxy.calls), 2)

    def test_lost_post_response_is_never_repeated(self):
        proxy = ClockProxy([(200, state()), DNCProxyError("No llegó la confirmación")])
        with self.assertRaisesRegex(DNCProxyError, "confirmación"):
            synchronize_clock(proxy, self.endpoint)
        self.assertEqual(sum(call[0] == "POST" for call in proxy.calls), 1)

    def test_pending_result_has_a_fixed_deadline_without_repeating_write(self):
        proxy = ClockProxy([(200, state())] + [(200, state("pending", request_id=REQUEST_ID))] * 50)
        with self.assertRaisesRegex(DNCProxyError, "no confirmó"):
            synchronize_clock(proxy, self.endpoint)
        self.assertLessEqual(self.elapsed, 8)
        self.assertEqual(sum(call[0] == "POST" for call in proxy.calls), 1)

    def test_invalid_time_or_missing_helper_never_sends_correction(self):
        for value in [state(utc_unix=True), state(utc_unix="2025"),
                      state(utc_unix=float("nan")), state(supported=False)]:
            with self.subTest(value=value):
                proxy = ClockProxy([(200, value)])
                with self.assertRaises(DNCProxyError):
                    synchronize_clock(proxy, self.endpoint)
                self.assertEqual(len(proxy.calls), 1)


if __name__ == "__main__":
    unittest.main()
