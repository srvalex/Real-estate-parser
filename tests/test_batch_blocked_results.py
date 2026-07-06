import unittest
from unittest.mock import patch

from scrapers.storia import StoriaScraper
from scrapers.imobiliare import ImobiliareRoScraper


class BatchBlockedResultsTests(unittest.TestCase):
    def test_storia_scrape_batch_keeps_blocked_results_for_reporting(self):
        with patch.object(StoriaScraper, '_fetch_batch_raw', return_value=[
            {"url": "https://www.storia.ro/oferta/test", "status": "blocked", "message": "timeout"},
        ]):
            result = StoriaScraper().scrape_batch(["https://www.storia.ro/oferta/test"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['url'], 'https://www.storia.ro/oferta/test')
        self.assertIsNone(result[0]['is_available'])

    def test_imobiliare_scrape_batch_keeps_blocked_results_for_reporting(self):
        with patch.object(ImobiliareRoScraper, '_fetch_batch_raw', return_value=[
            {"url": "https://www.imobiliare.ro/oferta/test", "status": "blocked", "message": "timeout"},
        ]):
            result = ImobiliareRoScraper().scrape_batch(["https://www.imobiliare.ro/oferta/test"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['url'], 'https://www.imobiliare.ro/oferta/test')
        self.assertIsNone(result[0]['is_available'])


if __name__ == '__main__':
    unittest.main()
