import unittest

from bench.analyze_g3 import compare


class ComparisonTests(unittest.TestCase):
    def test_three_way_comparison_keeps_same_capacity_policy_comparison(self):
        config = {
            "scenarios": {"trace": {}}, "seeds": [7],
            "modes": ["B0-L2", "B3-5s", "B0-L3"],
            "comparisons": [["B0-L2", "B3-5s"], ["B0-L2", "B0-L3"], ["B3-5s", "B0-L3"]],
            "mode_profiles": {
                "B0-L2": {"scheduler_mode": "B0", "max_loras": 2},
                "B3-5s": {"scheduler_mode": "B3", "max_loras": 2},
                "B0-L3": {"scheduler_mode": "B0", "max_loras": 3},
            },
            "targets": {"cold_p95_reduction_pct": 20, "max_goodput_loss_pct": 5,
                        "max_hot_p95_increase_ms": 1000},
        }
        rows = []
        for mode, slots, wait in (("B0-L2", 2, 1000), ("B3-5s", 2, 750), ("B0-L3", 3, 500)):
            rows.append({"mode": mode, "scenario": "trace", "seed": 7, "sha256": "same",
                         "max_loras": slots, "peak_active_loras_observed": slots,
                         "goodput_rps": 1, "policy_counts": {"cold_followup_selected": int(mode == "B3-5s")},
                         "groups": {"cold": {"queue_p95_ms": wait}, "hot": {"queue_p95_ms": 500}}})
        result = {row["comparison"]: row for row in compare(rows, config)}
        self.assertEqual(len(result), 3)
        self.assertEqual(result["B3-5s/B0-L2"]["b3_followups"], 1)
        self.assertNotIn("capacity_exercised", result["B3-5s/B0-L2"])
        self.assertTrue(result["B3-5s/B0-L2"]["meets_targets"])
        self.assertTrue(result["B0-L3/B0-L2"]["capacity_exercised"])
