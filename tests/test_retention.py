import datetime
import unittest

from backup import retention as r

D = datetime.date


class Retention(unittest.TestCase):
    def days(self, n, end=D(2026, 10, 4)):
        return [end - datetime.timedelta(days=i) for i in range(n)]

    def test_keeps_14_daily_plus_weekly_plus_monthly(self):
        today = D(2026, 10, 4)
        keep = r.keep_dates(self.days(400), today)
        self.assertTrue(all(d in keep for d in self.days(14)))
        old = [d for d in keep if (today - d).days >= 14]
        # roughly 8 weekly + up to 12 monthly beyond the daily window — never hundreds
        self.assertLess(len(old), 24)
        self.assertGreaterEqual(len(old), 8)
        self.assertLess(len(keep), 14 + 24)

    def test_missed_sunday_still_leaves_a_weekly(self):
        dates = [d for d in self.days(60) if d.weekday() != 6]      # every Sunday missing
        keep = r.keep_dates(dates, D(2026, 10, 4))
        weeks = {d.isocalendar()[:2] for d in keep if (D(2026, 10, 4) - d).days >= 14}
        self.assertGreaterEqual(len(weeks), 5)

    def test_never_prunes_newest_three_or_unknown_keys(self):
        keys = [f"sets/{d.isoformat()}/f.cms" for d in self.days(3)] + ["README.txt", "sets/notadate/x"]
        self.assertEqual(r.keys_to_delete(keys, D(2026, 10, 4)), [])

    def test_deletes_whole_old_sets_including_manifests(self):
        keys = []
        for d in self.days(100):
            keys += [f"sets/{d.isoformat()}/d1/a.sql.cms", f"sets/{d.isoformat()}/manifest-cloud.json"]
        doomed = r.keys_to_delete(keys, D(2026, 10, 4))
        self.assertTrue(doomed)
        dates = {r.set_date(k) for k in doomed}
        for d in dates:                                   # a set goes entirely or not at all
            self.assertEqual(sum(1 for k in doomed if r.set_date(k) == d), 2)
        self.assertNotIn(D(2026, 10, 4), dates)

    def test_empty_bucket_is_a_noop(self):
        self.assertEqual(r.keys_to_delete([], D(2026, 10, 4)), [])


if __name__ == "__main__":
    unittest.main()
