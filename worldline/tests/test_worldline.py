import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import worldline as w  # noqa: E402

HOUR = 3600
T0 = 1_800_000_000.0


def item(title, source="BBC", t=T0):
    return {"source": source, "title": title, "link": "", "ts": t}


class Scoring(unittest.TestCase):
    def test_direction(self):
        self.assertLess(w.lexicon_score("Missile attack kills dozens as war escalates")[0], -0.9)
        self.assertGreater(w.lexicon_score("Leaders sign peace deal and ceasefire")[0], 0.9)
        self.assertEqual(w.lexicon_score("Local bakery wins award")[0], 0.0)

    def test_severity_ordering(self):
        big = w.lexicon_score("Nuclear missile strike triggers war")[1]
        small = w.lexicon_score("Council debates parking rules")[1]
        self.assertGreater(big, 0.8)
        self.assertEqual(small, 0.05)

    def test_negation_flips_sign(self):
        self.assertGreater(w.lexicon_score("Diplomats avert war")[0], 0)

    def test_sports_ignored(self):
        self.assertEqual(w.lexicon_score("Football club declares war on rivals"), (0.0, 0.0))


class Mapping(unittest.TestCase):
    def test_zero_is_baseline(self):
        self.assertAlmostEqual(w.z_to_worldline(0), w.BASE, places=9)

    def test_continuous_and_monotonic(self):
        zs = [i / 20 for i in range(-200, 200)]
        vals = [w.z_to_worldline(z) for z in zs]
        self.assertTrue(all(a < b for a, b in zip(vals, vals[1:])))
        for a, b in zip(vals, vals[1:]):
            self.assertLess(abs(b - a), 0.06)  # no jumps

    def test_field_edge_and_bounds(self):
        self.assertAlmostEqual(w.z_to_worldline(-2.0), 1.0, places=9)
        self.assertEqual(w.field_name(w.z_to_worldline(-3)), "alpha")
        self.assertEqual(w.field_name(w.z_to_worldline(1)), "beta")
        self.assertLess(w.z_to_worldline(50), 2.0)
        self.assertGreater(w.z_to_worldline(-50), 0.0)


class Dynamics(unittest.TestCase):
    def feed_quiet(self, state, hours):
        t = T0
        for h in range(hours * 2):
            t = T0 + h * HOUR / 2
            batch = [item(f"Council debates parking rules number {h}", t=t),
                     item(f"Museum opens new exhibition week {h}", "NPR", t=t)]
            w.process(state, batch, t)
        return t

    def test_first_reading_is_exactly_baseline(self):
        s = w.fresh_state()
        w.process(s, [item("Floods and war dominate the news")], T0)
        self.assertEqual(f"{s['worldline']:.6f}", "1.048596")

    def test_crisis_burst_drops_then_recovers(self):
        s = w.fresh_state()
        t = self.feed_quiet(s, 72)
        before = s["worldline"]
        for k in range(12):  # six hours of heavy coverage from several outlets
            t += HOUR / 2
            batch = [item(f"Invasion launched, missile strikes kill hundreds wave {k}", src, t)
                     for src in ("BBC", "Guardian", "NPR", "CBC")]
            w.process(s, batch, t)
        low = s["worldline"]
        self.assertLess(low, before - 0.02)
        for k in range(24 * 14):  # two quiet weeks
            t += HOUR / 2
            w.process(s, [item(f"Museum opens exhibit {k}", t=t), item(f"Council vote {k}", "NPR", t=t)], t)
        self.assertGreater(s["worldline"], low)
        self.assertLess(abs(s["worldline"] - w.BASE), 0.05)

    def test_good_news_burst_raises(self):
        s = w.fresh_state()
        t = self.feed_quiet(s, 72)
        before = s["worldline"]
        for k in range(12):
            t += HOUR / 2
            w.process(s, [item(f"Peace deal signed, ceasefire holds, breakthrough cure wave {k}", src, t)
                          for src in ("BBC", "Guardian", "NPR", "CBC")], t)
        self.assertGreater(s["worldline"], before)

    def test_no_news_is_not_a_signal(self):
        s = w.fresh_state()
        t = self.feed_quiet(s, 48)
        for _ in range(48):  # a silent day
            t += HOUR / 2
            w.process(s, [], t)
        self.assertLess(abs(s["worldline"] - w.BASE), 0.03)

    def test_duplicates_counted_once(self):
        s = w.fresh_state()
        batch = [item("Earthquake strikes coastal city")]
        w.process(s, batch, T0)
        mass = s["sw_f"]
        w.process(s, batch, T0)  # same item re-fetched
        self.assertAlmostEqual(s["sw_f"], mass, places=9)

    def test_paraphrases_cluster_once(self):
        a = item("Massive earthquake strikes northern Japan coast", "BBC")
        b = item("Earthquake strikes Japan northern coast, thousands evacuated", "Guardian")
        c = item("Local council approves parking budget", "NPR")
        groups = w.cluster([a, b, c])
        self.assertEqual(sorted(len(g) for g in groups), [1, 2])

    def test_scorer_change_resets_normal(self):
        s = w.fresh_state()
        self.feed_quiet(s, 24)
        w.process(s, [item("x" * 5)], T0 + 100 * HOUR, "blend")  # blend falls back to lexicon w/o key
        self.assertEqual(s["scorer"], "blend")


class StoryPlot(unittest.TestCase):
    def test_story_d_direction_and_bounds(self):
        self.assertAlmostEqual(w.story_d(0, 0.5), w.BASE, places=9)
        self.assertLess(w.story_d(-1, 1), 1.0)
        self.assertGreater(w.story_d(1, 1), w.BASE)
        self.assertTrue(0 < w.story_d(-1, 1) < w.story_d(-0.2, 0.2) < w.story_d(1, 1) < 2)

    def test_z_fast_reported(self):
        s = w.fresh_state()
        step = w.process(s, [item("War erupts")], T0)
        self.assertIn("z_fast", step)
        self.assertEqual(step["scored"][0]["title"], "War erupts")


class StoryLog(unittest.TestCase):
    def test_merge_dedupes_filters_and_expires(self):
        r = {"ts": T0, "title": "War erupts", "source": "BBC", "link": "", "v": -1.0, "I": 0.9}
        low = dict(r, title="Parking", I=0.05)
        old = dict(r, title="Old", ts=T0 - 40 * 86400)
        rows = w.merge_stories([], [r, r, low, old], T0)
        self.assertEqual([x["title"] for x in rows], ["War erupts"])
        self.assertEqual(len(w.merge_stories(rows, [r], T0)), 1)

    def test_feed_list_size(self):
        self.assertGreaterEqual(len(w.FEEDS), 35)


class Output(unittest.TestCase):
    def test_eight_characters(self):
        s = w.fresh_state()
        step = w.process(s, [item("War erupts")], T0)
        out = w.build_output(s, step, T0)
        self.assertEqual(len(out["divergence"]), 8)
        self.assertEqual(out["divergence"][1], ".")
        self.assertTrue(out["calibrating"])

    def test_rss_and_atom_parse(self):
        rss = b"""<rss><channel><item><title>A  b</title><link>http://x</link>
                  <pubDate>Mon, 02 Jan 2023 10:00:00 GMT</pubDate></item></channel></rss>"""
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>C</title>
                   <link href="http://y"/><updated>2023-01-02T10:00:00Z</updated></entry></feed>"""
        self.assertEqual(w.parse_feed(rss, "S")[0]["title"], "A b")
        self.assertEqual(w.parse_feed(atom, "S")[0]["link"], "http://y")


if __name__ == "__main__":
    unittest.main()
