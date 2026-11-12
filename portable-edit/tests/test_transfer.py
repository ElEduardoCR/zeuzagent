import unittest
from zeuzedit_desktop.transfer import TransferTracker


class TransferTests(unittest.TestCase):
    def test_idle_and_old_success_do_not_unlock_uncertain_request(self):
        tracker = TransferTracker("new-unique.nc", request_pending=False)
        for status in [{"status": "idle"}, {"status": "success", "filename": "old.nc"}, {"status": "success", "filename": "new-unique.nc"}]:
            self.assertEqual(tracker.accept_status(status), "unknown")
            self.assertTrue(tracker.active)

    def test_matching_active_transfer_then_completion_resolves_uncertainty(self):
        tracker = TransferTracker("new-unique.nc", request_pending=False)
        self.assertEqual(tracker.accept_status({"status": "sending", "filename": "Agent Transfers/abc/new-unique.nc"}), "sending")
        self.assertEqual(tracker.accept_status({"status": "success", "filename": "new-unique.nc"}), "success")
        self.assertFalse(tracker.active)

    def test_acknowledged_completion_still_requires_matching_file(self):
        tracker = TransferTracker("new-unique.nc", request_pending=False, acknowledged=True)
        self.assertEqual(tracker.accept_status({"status": "success", "filename": "old.nc"}), "unknown")
        self.assertEqual(tracker.accept_status({"status": "success", "filename": "new-unique.nc"}), "success")

    def test_inflight_request_cannot_be_unlocked_by_terminal_status(self):
        tracker = TransferTracker("new-unique.nc", acknowledged=True)
        tracker.accept_status({"status": "success", "filename": "new-unique.nc"})
        self.assertTrue(tracker.active)

    def test_cancel_idle_does_not_disprove_a_delayed_uncertain_start(self):
        tracker = TransferTracker("new-unique.nc", request_pending=False, cancel_acknowledged=True)
        self.assertEqual(tracker.accept_status({"status": "idle"}), "unknown")
        tracker.acknowledged = True
        self.assertEqual(tracker.accept_status({"status": "idle"}), "unknown")
        tracker.observed = True
        self.assertEqual(tracker.accept_status({"status": "idle"}), "cancelled")
        self.assertFalse(tracker.active)


if __name__ == "__main__":
    unittest.main()
