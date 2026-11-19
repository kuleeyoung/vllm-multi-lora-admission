import unittest

from patches.admission_policy import AdmissionPolicy


class FollowupTests(unittest.TestCase):
    def setup_after_first_handoff(self, guard=10):
        events = []
        policy = AdmissionPolicy("B3", 5, 20, 1, lambda name, **fields: events.append(name),
                                 cold_ids={3, 4}, hot_guard_ns=guard, followup_ns=4)
        policy.queued("old-A", 0)
        policy.queued("C", 1)
        policy.queued("D", 2)
        policy.begin(6, [1, 2], [("old-A", 1), ("C", 3), ("D", 4)], 2)
        self.assertEqual(policy.pending.target, "C")
        self.assertEqual(policy.begin(7, [2], [("old-A", 1), ("C", 3), ("D", 4)], 2), "C")
        policy.admitted("C", 3, {2}, 2, 7)
        return policy, events

    def test_one_cold_followup_does_not_renew_preference(self):
        policy, events = self.setup_after_first_handoff()
        policy.begin(8, [2, 2, 3], [("old-A", 1), ("D", 4)], 2)
        self.assertEqual(policy.pending.target, "D")
        self.assertIn("cold_followup_selected", events)
        self.assertEqual(policy.begin(9, [2], [("old-A", 1), ("D", 4)], 2), "D")
        policy.admitted("D", 4, {2}, 2, 9)
        self.assertEqual(policy.followup_until, 0)

    def test_hot_guard_uses_original_order(self):
        policy, events = self.setup_after_first_handoff(guard=8)
        policy.begin(8, [2, 3], [("old-A", 1), ("D", 4)], 2)
        self.assertEqual(policy.pending.target, "old-A")
        self.assertIn("hot_guard_kept_order", events)
        self.assertEqual(policy.followup_until, 0)

    def test_unused_credit_expires(self):
        policy, events = self.setup_after_first_handoff(guard=100)
        policy.begin(11, [2, 3], [("old-A", 1), ("D", 4)], 2)
        self.assertEqual(policy.pending.target, "old-A")
        self.assertNotIn("cold_followup_selected", events)
