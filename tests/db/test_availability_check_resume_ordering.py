"""
get_listings_for_availability_check: stalest-first ordering + recency skip.

Background: avail-check-job's Cloud Run task timeout (4h) killed a ~27k
listing run partway through OLX, and the automatic retry restarted from the
top, redoing every listing the first attempt had just verified. Now that
last_seen_at is actually stamped on confirmed-live rechecks, the queue is
ordered stalest-first and can skip rows confirmed within the last N hours,
so a retry resumes.

Regression (2026-10-07): the first version sorted server-side with
.order("last_seen_at"). There is no index on that column, the query took
5-8s per page and hit Supabase's statement timeout (57014); the function
swallowed the error and returned [], so the scheduled 03:00 run logged
"Nothing to check" and status=success while doing no work at all. The sort
now happens in Python, and a failed page is retried and then RAISES.

Regression (2026-10-07, found while fixing the above): paging with .range()
(OFFSET) and no ORDER BY returned 25-40% duplicate rows -- measured against
the live table, 5-8k of ~20k queued listings were never returned in a given
fetch -- so every availability run silently skipped a large share of the
queue. Paging is now keyset on url (url > last ORDER BY url LIMIT n).
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import db_utils


def _row(url, last_seen_at=None, platform_id="olx", city="Bucuresti"):
    return {"url": url, "platform_id": platform_id, "city": city, "last_seen_at": last_seen_at}


def _chain(pages=None):
    """Mock PostgREST builder where every call returns itself; execute()
    yields the given pages in turn. An item that is an Exception is raised."""
    table = Mock()
    for name in ("select", "or_", "eq", "order", "range", "gt", "limit"):
        getattr(table, name).return_value = table
    outcomes = []
    for rows in (pages if pages is not None else [[]]):
        if isinstance(rows, Exception):
            outcomes.append(rows)
        else:
            r = Mock()
            r.data = rows
            outcomes.append(r)
    table.execute.side_effect = outcomes
    client = Mock()
    client.table.return_value = table
    return client, table


def _fetch(pages, **kwargs):
    client, table = _chain(pages)
    with patch("db_utils.get_client", return_value=client):
        rows = db_utils.get_listings_for_availability_check(**kwargs)
    return rows, table


class StalestFirstOrderingTests(unittest.TestCase):
    def test_never_asks_the_database_to_sort_by_last_seen_at(self):
        # last_seen_at has no index: a server-side sort on it hit the 8s
        # statement timeout. Ordering by url (indexed, for keyset paging) is fine.
        _, table = _fetch([[_row("https://a")]])
        for call in table.order.call_args_list:
            self.assertEqual(call.args, ("url",))

    def test_never_seen_rows_come_first_then_oldest_to_newest(self):
        rows, _ = _fetch([[
            _row("https://new", "2026-10-06T20:00:00+00:00"),
            _row("https://never", None),
            _row("https://old", "2026-09-01T08:00:00+00:00"),
            _row("https://mid", "2026-10-01T08:00:00+00:00"),
        ]])
        self.assertEqual(
            [r["url"] for r in rows],
            ["https://never", "https://old", "https://mid", "https://new"],
        )

    def test_equal_stamps_are_tiebroken_by_url(self):
        rows, _ = _fetch([[_row("https://b", "2026-10-01T00:00:00+00:00"),
                           _row("https://a", "2026-10-01T00:00:00+00:00")]])
        self.assertEqual([r["url"] for r in rows], ["https://a", "https://b"])

    def test_output_shape_has_no_last_seen_at(self):
        rows, _ = _fetch([[_row("https://a", "2026-10-01T00:00:00+00:00", platform_id="storia", city="Iasi")]])
        self.assertEqual(rows, [{"url": "https://a", "platform_id": "storia", "city": "Iasi"}])

    def test_select_asks_for_last_seen_at_so_it_can_sort(self):
        _, table = _fetch([[]])
        self.assertIn("last_seen_at", table.select.call_args.args[0])

    def test_limit_returns_the_stalest_rows_not_the_first_fetched(self):
        rows, _ = _fetch([[
            _row("https://fresh", "2026-10-06T20:00:00+00:00"),
            _row("https://never", None),
            _row("https://stale", "2026-08-01T00:00:00+00:00"),
        ]], limit=2)
        self.assertEqual([r["url"] for r in rows], ["https://never", "https://stale"])

    def test_platform_filter_is_forwarded(self):
        _, table = _fetch([[]], platform_id="storia")
        table.eq.assert_called_once_with("platform_id", "storia")



class KeysetPaginationTests(unittest.TestCase):
    def test_pages_by_url_keyset_not_offset(self):
        page1 = [_row(f"https://x/{i:04d}") for i in range(1000)]
        page2 = [_row("https://x/9999")]
        rows, table = _fetch([page1, page2])

        self.assertEqual(len(rows), 1001)
        table.range.assert_not_called()  # OFFSET paging returned duplicates + missed rows
        self.assertEqual([c.args for c in table.limit.call_args_list], [(1000,), (1000,)])
        # first page has no lower bound; the second starts after the last url seen
        self.assertEqual([c.args for c in table.gt.call_args_list], [("url", "https://x/0999")])

    def test_every_row_is_returned_exactly_once_across_pages(self):
        pages = [[_row(f"https://x/{p}-{i:04d}") for i in range(1000)] for p in range(3)] + [[_row("https://x/z")]]
        rows, _ = _fetch(pages)
        urls = [r["url"] for r in rows]
        self.assertEqual(len(urls), 3001)
        self.assertEqual(len(set(urls)), 3001)

    def test_an_exactly_full_last_page_costs_one_extra_empty_query(self):
        rows, table = _fetch([[_row(f"https://x/{i:04d}") for i in range(1000)], []])
        self.assertEqual(len(rows), 1000)
        self.assertEqual(table.execute.call_count, 2)


class SkipRecentlySeenTests(unittest.TestCase):
    def test_no_recency_filter_by_default(self):
        _, table = _fetch([[]])
        self.assertEqual(table.or_.call_count, 1)  # only the is_available filter

    def test_zero_hours_means_no_recency_filter(self):
        _, table = _fetch([[]], skip_seen_within_hours=0)
        self.assertEqual(table.or_.call_count, 1)

    def test_recency_filter_keeps_null_and_older_than_cutoff(self):
        before = datetime.now(timezone.utc)
        _, table = _fetch([[]], skip_seen_within_hours=12)
        after = datetime.now(timezone.utc)

        self.assertEqual(table.or_.call_count, 2)
        self.assertEqual(
            set(table.or_.call_args_list[0].args[0].split(",")),
            {"is_available.eq.1", "is_available.eq.-1", "is_available.is.null"},
        )
        null_clause, lt_clause = table.or_.call_args_list[1].args[0].split(",")
        self.assertEqual(null_clause, "last_seen_at.is.null")
        self.assertTrue(lt_clause.startswith("last_seen_at.lt."))

        cutoff = datetime.strptime(
            lt_clause.removeprefix("last_seen_at.lt."), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        slack = timedelta(seconds=1)
        self.assertGreaterEqual(cutoff, before - timedelta(hours=12) - slack)
        self.assertLessEqual(cutoff, after - timedelta(hours=12) + slack)

    def test_cutoff_has_no_plus_or_spaces_that_break_the_query_string(self):
        _, table = _fetch([[]], skip_seen_within_hours=1.5)
        clause = table.or_.call_args_list[1].args[0]
        self.assertNotIn("+", clause)
        self.assertNotIn(" ", clause)

    def test_filter_is_reapplied_on_every_page(self):
        full = [_row(f"https://x/{i:04d}") for i in range(1000)]
        rows, table = _fetch([full, [_row("https://x/last")]], skip_seen_within_hours=12)

        self.assertEqual(len(rows), 1001)
        self.assertEqual(table.or_.call_count, 4)  # status + recency, per page


class FailureHandlingTests(unittest.TestCase):
    def setUp(self):
        sleep = patch("db_utils.time.sleep")
        self.mock_sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_a_transient_page_failure_is_retried(self):
        rows, table = _fetch([RuntimeError("canceling statement due to statement timeout"),
                              [_row("https://a")]])
        self.assertEqual([r["url"] for r in rows], ["https://a"])
        self.assertEqual(table.execute.call_count, 2)

    def test_two_failures_in_a_row_still_recover_on_the_third_attempt(self):
        rows, table = _fetch([RuntimeError("x"), RuntimeError("x"), [_row("https://a")]])
        self.assertEqual([r["url"] for r in rows], ["https://a"])
        self.assertEqual(table.execute.call_count, 3)
        self.assertEqual([c.args[0] for c in self.mock_sleep.call_args_list], [1, 2])

    def test_a_persistent_failure_raises_instead_of_returning_nothing(self):
        client, table = _chain([RuntimeError("boom")] * 3)
        with patch("db_utils.get_client", return_value=client):
            with self.assertRaises(RuntimeError):
                db_utils.get_listings_for_availability_check()
        self.assertEqual(table.execute.call_count, 3)

    def test_a_failure_on_a_later_page_does_not_return_a_partial_queue(self):
        full = [_row(f"https://x/{i}") for i in range(1000)]
        client, _ = _chain([full] + [RuntimeError("x")] * 3)
        with patch("db_utils.get_client", return_value=client):
            with self.assertRaises(RuntimeError):
                db_utils.get_listings_for_availability_check()


class RealBuilderParamsTests(unittest.TestCase):
    """Mocks accept any call order; this checks the real postgrest-py builder
    emits the query we mean: two ANDed `or` params, keyset on url, no OFFSET,
    and no ORDER BY on the unindexed last_seen_at."""

    def _params(self, last_page_rows):
        from postgrest import SyncPostgrestClient

        real = SyncPostgrestClient("http://localhost:1/rest/v1", headers={"apikey": "x"})
        captured = []

        def fake_execute(builder_self):
            captured.append(str(builder_self.request.params))
            return Mock(data=last_page_rows if len(captured) == 1 else [])

        client = Mock()
        client.table.side_effect = real.table
        with patch("db_utils.get_client", return_value=client), \
             patch("postgrest._sync.request_builder.SyncQueryRequestBuilder.execute", fake_execute):
            db_utils.get_listings_for_availability_check(skip_seen_within_hours=12)
        return captured

    def test_first_page_params(self):
        (params,) = self._params([])
        self.assertEqual(params.count("or="), 2)
        self.assertIn("order=url.asc", params)
        self.assertNotIn("last_seen_at.asc", params)
        self.assertNotIn("offset=", params)
        self.assertIn("limit=1000", params)
        self.assertNotIn("url=gt.", params)

    def test_second_page_adds_the_keyset_bound(self):
        full = [{"url": f"https://x/{i:04d}", "platform_id": "olx", "city": "c", "last_seen_at": None} for i in range(1000)]
        first, second = self._params(full)
        self.assertIn("url=gt.https%3A%2F%2Fx%2F0999", second)
        self.assertNotIn("offset=", second)


if __name__ == "__main__":
    unittest.main()
