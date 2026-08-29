"""
Unit tests for OLXScraper's "ad-parameters-container" extraction
(scrapers/olx.py: _extract_params, _PARAM_LABELS).

ENRICHMENT_PLAN.md Phase 1: OLX's extras column is always NULL (no backing
JSON API — see query_model.py) but every listing page carries a small
native params block that was previously discarded entirely. Confirmed live
2026-08-29 against two real listings (a Studio and a Garsoniera, both
Bucharest) — identical container shape and label set on both:

    <div data-testid="ad-parameters-container">
      <p><span>Persoana fizica</span></p>            <- seller type, no colon
      <p>Compartimentare: Decomandat</p>
      <p>Suprafata utila: 49 m²</p>
      <p>An constructie: Dupa 2000</p>
      <p>Etaj: Parter</p>
    </div>

_extract_params maps these onto the raw field names _clean_record
(db_utils.py) already knows how to fold: "m" -> area_sqm, "floor_no" ->
floor, "build_year" -> year_built (floor/year_built are TEXT columns in
scripts/supabase_schema.sql, so fuzzy values like "Parter" or "Dupa 2000"
are stored as-is, no numeric parsing attempted). "compartimentare" has no
canonical column and folds into `extras` automatically.
"""
import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from scrapers.olx import OLXScraper, _extract_params

# Real container markup, captured live 2026-08-29 from a Studio listing
# (Str. Rodnei, Targu Mures) via the OLX listing the enrichment plan was
# scoped against.
REAL_PARAMS_HTML = """
<div data-nx-name="ListContainer" data-testid="ad-parameters-container" class="css-1xsisw9">
  <p data-nx-name="P3" class="css-odhutu"><span>Persoana fizica</span></p>
  <p data-nx-name="P3" class="css-odhutu">Compartimentare: Decomandat</p>
  <p data-nx-name="P3" class="css-odhutu">Suprafata utila: 49 m²</p>
  <p data-nx-name="P3" class="css-odhutu">An constructie: Dupa 2000</p>
  <p data-nx-name="P3" class="css-odhutu">Etaj: Parter</p>
</div>
"""

# Second real sample (a Bucharest Garsoniera) — same label set, different
# (non-fuzzy) values, confirms the mapping isn't overfit to the first page.
REAL_PARAMS_HTML_2 = """
<div data-testid="ad-parameters-container">
  <p><span>Persoana fizica</span></p>
  <p>Compartimentare: Decomandat</p>
  <p>Suprafata utila: 42 m²</p>
  <p>An constructie: 1990 – 2000</p>
  <p>Etaj: 3</p>
</div>
"""

FULL_LISTING_HTML = """
<html><body>
<div data-cy="offer_title"><h4>Studio premium Rodnei</h4></div>
<div data-testid="ad-price-container"><h3>500 EUR</h3></div>
<div data-cy="ad_description">Studio modern, complet mobilat.</div>
<div data-cy="ad-footer-bar-section"><span>ID<i></i>305868205</span></div>
<div data-testid="ad-parameters-container">
  <p><span>Persoana fizica</span></p>
  <p>Compartimentare: Decomandat</p>
  <p>Suprafata utila: 49 m²</p>
  <p>An constructie: Dupa 2000</p>
  <p>Etaj: Parter</p>
</div>
</body></html>
"""


def _fake_response(status_code: int, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class ExtractParamsTests(unittest.TestCase):
    def test_full_container_maps_all_four_labels(self):
        soup = BeautifulSoup(REAL_PARAMS_HTML, "html.parser")
        self.assertEqual(
            _extract_params(soup),
            {
                "compartimentare": "Decomandat",
                "m": "49 m²",
                "build_year": "Dupa 2000",
                "floor_no": "Parter",
            },
        )

    def test_numeric_floor_and_year_range_pass_through_as_raw_text(self):
        """floor/year_built are TEXT columns — no numeric coercion is
        attempted, so a range like '1990 – 2000' or a plain '3' are both
        just stored as scraped."""
        soup = BeautifulSoup(REAL_PARAMS_HTML_2, "html.parser")
        params = _extract_params(soup)
        self.assertEqual(params["build_year"], "1990 – 2000")
        self.assertEqual(params["floor_no"], "3")

    def test_seller_type_line_without_colon_is_skipped(self):
        soup = BeautifulSoup(REAL_PARAMS_HTML, "html.parser")
        params = _extract_params(soup)
        self.assertNotIn("Persoana fizica", params.values())
        self.assertEqual(len(params), 4)  # only the 4 real key:value params

    def test_missing_container_returns_empty_dict(self):
        soup = BeautifulSoup("<html><body><p>no params here</p></body></html>", "html.parser")
        self.assertEqual(_extract_params(soup), {})

    def test_partial_container_only_maps_present_labels(self):
        html = '<div data-testid="ad-parameters-container"><p>Etaj: 5</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(_extract_params(soup), {"floor_no": "5"})

    def test_accented_label_variant_also_matches(self):
        html = (
            '<div data-testid="ad-parameters-container">'
            "<p>Suprafață utilă: 60 m²</p>"
            "<p>An construcție: 2015</p>"
            "</div>"
        )
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(_extract_params(soup), {"m": "60 m²", "build_year": "2015"})

    def test_unknown_label_is_ignored(self):
        html = '<div data-testid="ad-parameters-container"><p>Cod ofertant: XYZ123</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        self.assertEqual(_extract_params(soup), {})


class ScrapeListingParamsIntegrationTests(unittest.TestCase):
    def test_params_are_merged_into_scraped_listing_data(self):
        with patch(
            "curl_cffi.requests.get", return_value=_fake_response(200, text=FULL_LISTING_HTML)
        ):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test-params.html"
            )
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertEqual(data["m"], "49 m²")
        self.assertEqual(data["floor_no"], "Parter")
        self.assertEqual(data["build_year"], "Dupa 2000")
        self.assertEqual(data["compartimentare"], "Decomandat")
        # Untouched: existing fields still present alongside the new ones.
        self.assertEqual(data["title"], "Studio premium Rodnei")

    def test_listing_without_params_container_still_parses_successfully(self):
        """Older/different-template listings with no params block at all
        must not break scraping — params are purely additive."""
        html_no_params = FULL_LISTING_HTML.split('<div data-testid="ad-parameters-container">')[0] + "</body></html>"
        with patch(
            "curl_cffi.requests.get", return_value=_fake_response(200, text=html_no_params)
        ):
            result = OLXScraper().scrape_listing_with_status(
                "https://www.olx.ro/d/oferta/test-no-params.html"
            )
        self.assertEqual(result["status"], "success")
        for key in ("m", "floor_no", "build_year", "compartimentare"):
            self.assertNotIn(key, result["data"])


if __name__ == "__main__":
    unittest.main()
