import unittest

from scripts.get_rendered_description import classify_storia_page


class StoriaArchiveDetectionTests(unittest.TestCase):

    def test_expired_marker_wins_over_next_data(self):
        result = classify_storia_page(
            content='''<html><body>
                <script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {"ad": {"id": 1}}}}</script>
                <div data-sentry-element="ExpiredAdContentLayout"></div>
            </body></html>''',
            url='https://www.storia.ro/ro/oferta/test'
        )
        self.assertEqual(result['status'], 'expired')

    def test_live_listing_with_next_data_is_success(self):
        result = classify_storia_page(
            content='''<html><body>
                <script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {"ad": {"id": 1}}}}</script>
            </body></html>''',
            url='https://www.storia.ro/ro/oferta/test'
        )
        self.assertEqual(result['status'], 'success')

    def test_next_data_with_no_ad_key_is_expired(self):
        """Redirected to search/home page — __NEXT_DATA__ present but no ad key."""
        result = classify_storia_page(
            content='''<html><body>
                <script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {}}}</script>
            </body></html>''',
            url='https://www.storia.ro/ro/oferta/test'
        )
        self.assertEqual(result['status'], 'expired')

    def test_next_data_with_empty_ad_is_expired(self):
        """ad key present but empty dict — no listing id means page was removed."""
        result = classify_storia_page(
            content='''<html><body>
                <script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {"ad": {}}}}</script>
            </body></html>''',
            url='https://www.storia.ro/ro/oferta/test'
        )
        self.assertEqual(result['status'], 'expired')

    def test_no_next_data_and_no_expired_marker_is_blocked(self):
        """Cloudflare / bot-protection page — no __NEXT_DATA__, no expiry marker."""
        result = classify_storia_page(
            content='<html><body>Just a moment...</body></html>',
            url='https://www.storia.ro/ro/oferta/test'
        )
        self.assertEqual(result['status'], 'blocked')

    def test_anunt_arhivat_romanian_marker(self):
        result = classify_storia_page(
            content='<html><body>Anunț arhivat. Acest anunț nu mai este disponibil.</body></html>',
            url='https://www.storia.ro/ro/oferta/test'
        )
        self.assertEqual(result['status'], 'expired')


if __name__ == '__main__':
    unittest.main()
