"""
Regression tests for classify_imobiliare_ld_graph in
scripts/get_imobiliare_listing.py.

Bug: a genuinely removed Imobiliare listing does not redirect and shows no
text marker — the site silently serves a search-results page's content at
the exact same URL. The old code only checked "is Product/Offer present?"
and fell straight to "blocked" when they were absent, with no way to tell
that apart from a real bot-challenge stub with no JSON-LD at all. Confirmed
live (2026-08-22) against a user-reported removed listing: its JSON-LD
@graph carries @type ["Organization", "SearchResultsPage"], never
"Product"/"Offer".

Fix: classify_imobiliare_ld_graph treats a positively-identified
SearchResultsPage node (with no Product/Offer) as expired, and reserves
"blocked" for the case where there's no JSON-LD signal to classify from at
all — the same "never assume expired without positive evidence" principle
already applied to Storia and OLX.
"""
import unittest

from scripts.get_imobiliare_listing import classify_imobiliare_ld_graph


class ImobiliareLdGraphClassificationTests(unittest.TestCase):
    def test_search_results_page_graph_is_expired(self):
        """Real shape of a genuinely removed listing's JSON-LD graph."""
        result = classify_imobiliare_ld_graph(["Organization", "SearchResultsPage"])
        self.assertEqual(result, {"status": "expired"})

    def test_no_ld_nodes_at_all_is_blocked(self):
        """A bot-challenge stub page has no JSON-LD whatsoever — must not be
        confused with a genuine removal."""
        result = classify_imobiliare_ld_graph([])
        self.assertEqual(result["status"], "blocked")

    def test_product_present_returns_none_to_proceed_with_extraction(self):
        result = classify_imobiliare_ld_graph(["Product", "Offer", "RealEstateListing"])
        self.assertIsNone(result)

    def test_offer_alone_returns_none_to_proceed_with_extraction(self):
        result = classify_imobiliare_ld_graph(["Offer"])
        self.assertIsNone(result)

    def test_unrecognised_graph_with_no_search_page_marker_defaults_to_blocked(self):
        """Structured data present but neither a listing nor a recognised
        search page — safe default is blocked, never expired."""
        result = classify_imobiliare_ld_graph(["WebPage", "BreadcrumbList"])
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
