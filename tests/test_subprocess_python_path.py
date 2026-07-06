import sys
import unittest
from unittest.mock import Mock, patch

from scrapers.imobiliare import ImobiliareRoScraper
from scrapers.storia import StoriaScraper


class SubprocessPythonPathTests(unittest.TestCase):
    def test_storia_batch_makes_direct_requests_without_subprocess(self):
        """Storia was refactored away from a Playwright subprocess to direct
        curl_cffi requests (see scrapers/storia.py _fetch_batch_raw) — assert
        that architecture instead of a subprocess call that no longer happens."""
        fake_response = Mock()
        fake_response.url = 'https://www.storia.ro/ro/oferta/test'
        fake_response.text = '<html></html>'

        with patch('scrapers.storia.cffi_requests.get', return_value=fake_response) as get:
            StoriaScraper()._fetch_batch_raw(['https://www.storia.ro/ro/oferta/test'])

        get.assert_called_once()
        self.assertFalse(hasattr(__import__('scrapers.storia', fromlist=['x']), 'subprocess'))

    def test_imobiliare_batch_uses_current_python_executable(self):
        fake_proc = Mock()
        fake_proc.communicate.return_value = ('[]', '')

        with patch('scrapers.imobiliare.subprocess.Popen', return_value=fake_proc) as popen:
            ImobiliareRoScraper()._fetch_batch_raw(['https://www.imobiliare.ro/oferta/test'])

        self.assertEqual(popen.call_args[0][0][0], sys.executable)


if __name__ == '__main__':
    unittest.main()
