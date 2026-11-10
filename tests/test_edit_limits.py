import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import edit_limits as el


class EditLimitTests(unittest.TestCase):
    def test_resubmit_counts_only_changed_answers_and_stops_at_two(self):
        counts = {}
        mine, counts, changed, blocked = el.apply_resubmit(["1", "2", "3"], ["1", "4", "3"], counts)
        self.assertEqual((mine, changed, blocked), (["1", "4", "3"], [2], []))
        mine, counts, changed, blocked = el.apply_resubmit(mine, ["1", "5", "2"], counts)
        self.assertEqual((changed, blocked), ([2, 3], []))
        self.assertEqual(counts, {2: 2, 3: 1})
        # 2번 문항은 이미 두 번 고쳤다 → 바꾸려 해도 앞의 답 그대로
        mine, counts, changed, blocked = el.apply_resubmit(mine, ["1", "1", "3"], counts)
        self.assertEqual(mine, ["1", "5", "3"])
        self.assertEqual((changed, blocked), ([3], [2]))
        self.assertEqual(el.locked_list(counts), [2, 3])

    def test_retry_shares_the_same_counter(self):
        counts = el.load_counts({"q_edits": {"4": 1, "x": 3, "7": "bad"}})
        self.assertEqual(counts, {4: 1})
        allowed, counts, blocked = el.take_retry([4, 6], counts)
        self.assertEqual((allowed, blocked), ([4, 6], []))
        allowed, counts, blocked = el.take_retry([4, 6], counts)
        self.assertEqual((allowed, blocked), ([6], [4]))
        self.assertEqual(el.dump_counts(counts), {"4": 2, "6": 2})
        self.assertTrue(el.is_locked(counts, 6))


if __name__ == "__main__":
    unittest.main()
