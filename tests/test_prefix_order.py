import json
from pathlib import Path
import unittest

from bench.analyze_arrival_order import verify_order_pair
from bench.run_g3 import workload


class PrefixOrderTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "configs/g3-prefix-order.json"
        self.config = json.loads(source.read_bytes())
        self.seed = self.config["seeds"][0]
        self.start = self.config["shared_suffix_from_index"]
        self.hot, self.cold = (
            workload(self.config, scenario, self.seed) for scenario in self.config["scenarios"].values()
        )

    def test_only_first_four_labels_can_differ(self):
        verify_order_pair(self.hot, self.cold, self.start)
        self.assertEqual([row["model"] for row in self.hot[:4]], list("ABCD"))
        self.assertEqual([row["model"] for row in self.cold[:4]], list("CDAB"))
        self.assertEqual(self.hot[4:], self.cold[4:])
        self.assertEqual(len(self.hot), 64)

    def test_suffix_swap_rejected_even_if_counts_match(self):
        self.cold[4]["model"], self.cold[5]["model"] = self.cold[5]["model"], self.cold[4]["model"]
        with self.assertRaisesRegex(ValueError, "after the experimental prefix"):
            verify_order_pair(self.hot, self.cold, self.start)

    def test_rejects_changed_prompt(self):
        self.cold[0]["prompt"] = "changed prompt"
        with self.assertRaisesRegex(ValueError, "non-adapter request fields"):
            verify_order_pair(self.hot, self.cold, self.start)
