import unittest

from scripts.get_imobiliare_listing import classify_imobiliare_page


class ImobiliareUnavailableDetectionTests(unittest.TestCase):

    def test_unavailable_text_marks_listing_expired(self):
        result = classify_imobiliare_page(
            content='<html><body>În acest moment, nu se primesc cereri pentru această proprietate.</body></html>',
            requested_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
            final_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
        )
        self.assertEqual(result['status'], 'expired')

    def test_deja_inchiriat_marker(self):
        result = classify_imobiliare_page(
            content='<html><body>Această proprietate a fost deja închiriată.</body></html>',
            requested_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
            final_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
        )
        self.assertEqual(result['status'], 'expired')

    def test_homepage_redirect_is_blocked_not_expired(self):
        """Proxy block redirects to homepage — must NOT be classified as expired."""
        result = classify_imobiliare_page(
            content='<html><body>Imobiliare homepage content</body></html>',
            requested_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
            final_url='https://www.imobiliare.ro/',
        )
        self.assertEqual(result['status'], 'blocked')

    def test_external_redirect_is_blocked(self):
        """Redirect to captcha/external domain is blocked, not expired."""
        result = classify_imobiliare_page(
            content='<html><body>Captcha</body></html>',
            requested_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
            final_url='https://captcha.example.com/',
        )
        self.assertEqual(result['status'], 'blocked')

    def test_no_markers_no_redirect_is_blocked(self):
        """Live page with no markers and no redirect — blocked pending JSON-LD check."""
        result = classify_imobiliare_page(
            content='<html><body><h1>Nice apartment</h1></body></html>',
            requested_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
            final_url='https://www.imobiliare.ro/inchirieri-apartamente/oferta/test-123',
        )
        self.assertEqual(result['status'], 'blocked')

    def test_footer_copyright_notice_is_not_falsely_expired(self):
        """Regression: every real Imobiliare page's footer reads '(c) Realmedia
        Network ... Toate drepturile rezervate.' (all rights reserved). The
        'rezervat' marker matches this on every single live listing, which is
        why 100% of imobiliare rows in prod ended up is_available=0."""
        result = classify_imobiliare_page(
            content=(
                '<html><body><h1>Apartament 2 camere, Obor</h1>'
                '<p>Toate drepturile rezervate.</p>'
                '</body></html>'
            ),
            requested_url='https://www.imobiliare.ro/oferta/apartament-test-123',
            final_url='https://www.imobiliare.ro/oferta/apartament-test-123',
        )
        self.assertNotEqual(
            result['status'], 'expired',
            "Footer copyright text ('rezervate') falsely triggered the "
            "'rezervat' unavailable-marker on a live listing page",
        )


if __name__ == '__main__':
    unittest.main()
