import unittest
from lib.save_stats import stage_from_level, level_from_stage


class StageTests(unittest.TestCase):
    def test_completed_levels_match_displayed_stage(self):
        for completed, stage in ((0, 1), (5, 6), (6, 7), (99, 100)):
            with self.subTest(completed=completed):
                self.assertEqual(stage_from_level(completed), stage)
                self.assertEqual(level_from_stage(str(stage)), completed)

    def test_invalid_stage_is_rejected(self):
        for value in ('0', '-1', '1.5', '', 'abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                level_from_stage(value)
