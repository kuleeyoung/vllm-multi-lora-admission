import unittest

from patches.admission_policy import AdmissionPolicy


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.events = []

    def policy(self, mode="B2"):
        return AdmissionPolicy(mode, 5, 20, 10,
                               lambda event, **fields: self.events.append((event, fields)))

    def trigger(self, p):
        p.queued("C", 0)
        p.queued("D", 1)
        p.begin(6, [1, 1, 2], [("D", 4), ("C", 3)], 2)
        self.assertEqual((p.pending.target, p.pending.victim), ("C", 2))

    def test_b1_lets_earlier_hot_request_take_slot(self):
        p = self.policy("B1")
        self.trigger(p)
        self.assertTrue(p.should_defer(2))
        self.assertFalse(p.should_defer(1))
        self.assertIsNone(p.begin(7, [1], [("C", 3), ("D", 4)], 2))
        self.assertFalse(p.should_defer(2))
        p.admitted("earlier-B", 2, {1}, 2, 7)
        self.assertIsNone(p.pending)
        self.assertEqual(self.events[-1][1]["reason"], "slot_taken")

    def test_b2_prefers_oldest_and_finishes_only_on_admission(self):
        p = self.policy()
        self.trigger(p)
        self.assertIsNone(p.begin(7, [1, 2], [("C", 3), ("D", 4)], 2))
        self.assertEqual(p.begin(8, [1], [("C", 3), ("D", 4)], 2), "C")
        self.assertIsNotNone(p.pending)
        p.admitted("C", 3, {1}, 2, 9)
        self.assertIsNone(p.pending)
        self.assertNotIn("C", p.arrivals)
        self.assertEqual([name for name, _ in self.events],
                         ["drain_started", "slot_released", "target_admitted", "reservation_closed"])

    def test_token_kv_and_full_request_capacity_clear_released_reservation(self):
        for reason in ("token_budget", "kv_budget", "round_resources_unavailable"):
            with self.subTest(reason=reason):
                p = self.policy()
                self.trigger(p)
                self.assertEqual(p.begin(7, [1], [("C", 3), ("D", 4)], 2), "C")
                p.rejected(7, reason)
                self.assertIsNone(p.pending)
                self.assertFalse(p.should_defer(2))
                self.assertEqual(self.events[-1][1]["reason"], reason)
                self.assertIn("C", p.arrivals)

    def test_cancel_cleans_state_and_expiry_enforces_cooldown(self):
        p = self.policy()
        self.trigger(p)
        p.finished("C", 8)
        self.assertNotIn("C", p.arrivals)
        self.assertIsNone(p.pending)
        self.assertFalse(p.should_defer(2))
        p.begin(9, [1, 2], [("D", 4)], 2)
        p.begin(29, [1, 2], [("D", 4)], 2)
        self.assertEqual(self.events[-1][1]["reason"], "expired")
        p.begin(30, [1, 2], [("D", 4)], 2)
        self.assertIsNone(p.pending)
        p.begin(39, [1, 2], [("D", 4)], 2)
        self.assertEqual(p.pending.target, "D")

    def test_underfilled_active_target_and_threshold_do_not_trigger(self):
        p = self.policy()
        p.queued("C", 0)
        for time, active in [(4, [1, 2]), (9, [1]), (9, [1, 3])]:
            self.assertIsNone(p.begin(time, active, [("C", 3)], 2))
            self.assertIsNone(p.pending)
        p.begin(9, [2, 1], [("C", 3)], 2)
        self.assertEqual(p.pending.victim, 1)

    def test_other_adapter_admission_with_spare_capacity_is_not_a_missed_slot(self):
        p = self.policy("B1")
        self.trigger(p)
        p.begin(7, [], [("C", 3), ("D", 4)], 2)
        p.admitted("D", 4, set(), 2, 8)
        self.assertEqual(p.pending.target, "C")
        p.admitted("C", 3, {4}, 2, 9)
        self.assertIsNone(p.pending)
        self.assertNotIn("slot_taken", [name for name, _ in self.events])

    def test_unavailable_target_and_upstream_preemption_release_the_victim(self):
        p = self.policy()
        self.trigger(p)
        p.finished("unrelated", 7)
        self.assertTrue(p.should_defer(2))
        p.begin(8, [1, 2], [("D", 4)], 2)
        self.assertEqual(self.events[-1][1]["reason"], "target_unavailable")
        p.begin(9, [1, 2], [("D", 4)], 2)
        self.assertTrue(p.should_defer(1))
        p.clear(10, "upstream_preemption")
        self.assertFalse(p.should_defer(1))
