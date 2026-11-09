"""
Tests for ProxyRotator.from_webshare / from_config.

Background: the static PROXY_LIST secret went stale (every proxy answered
HTTP 407), so the availability check and crawl silently ran unproxied and
Storia blocked ~98% of requests. The proxy list is now pulled from the
Webshare API per run, with PROXY_LIST kept only as a fallback.
"""
import os
import unittest
from unittest.mock import patch, MagicMock

from crawler import ProxyRotator


def _page(results, next_url=None):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"count": len(results), "next": next_url, "results": results}
    return resp


def _proxy(addr, valid=True, user="u", pw="p", port=8000):
    return {"proxy_address": addr, "port": port, "username": user, "password": pw, "valid": valid}


class FromWebshareTests(unittest.TestCase):
    def test_builds_authenticated_proxy_urls(self):
        with patch("requests.get", return_value=_page([_proxy("1.2.3.4", user="bob", pw="s3", port=6000)])):
            rotator = ProxyRotator.from_webshare("KEY")
        self.assertEqual(rotator._proxies, ["http://bob:s3@1.2.3.4:6000"])

    def test_sends_token_auth_header_and_direct_mode(self):
        with patch("requests.get", return_value=_page([])) as mock_get:
            ProxyRotator.from_webshare("KEY")
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://proxy.webshare.io/api/v2/proxy/list/")
        self.assertEqual(kwargs["headers"], {"Authorization": "Token KEY"})
        self.assertEqual(kwargs["params"]["mode"], "direct")

    def test_drops_proxies_webshare_marks_invalid(self):
        page = _page([_proxy("1.1.1.1", valid=True), _proxy("2.2.2.2", valid=False)])
        with patch("requests.get", return_value=page):
            rotator = ProxyRotator.from_webshare("KEY")
        self.assertEqual(len(rotator._proxies), 1)
        self.assertIn("1.1.1.1", rotator._proxies[0])

    def test_follows_pagination_via_next_url(self):
        p1 = _page([_proxy("1.1.1.1")], next_url="https://proxy.webshare.io/api/v2/proxy/list/?page=2")
        p2 = _page([_proxy("2.2.2.2")], next_url=None)
        with patch("requests.get", side_effect=[p1, p2]) as mock_get:
            rotator = ProxyRotator.from_webshare("KEY")
        self.assertEqual(len(rotator._proxies), 2)
        self.assertEqual(mock_get.call_count, 2)
        # second call uses the full `next` URL, no params re-applied
        self.assertEqual(mock_get.call_args_list[1].args[0], "https://proxy.webshare.io/api/v2/proxy/list/?page=2")
        self.assertIsNone(mock_get.call_args_list[1].kwargs["params"])

    def test_http_error_propagates(self):
        bad = MagicMock()
        bad.raise_for_status.side_effect = RuntimeError("401")
        with patch("requests.get", return_value=bad):
            with self.assertRaises(RuntimeError):
                ProxyRotator.from_webshare("KEY")


class FromConfigTests(unittest.TestCase):
    def _env(self, **kw):
        return patch.dict(os.environ, kw, clear=True)

    def test_proxy_file_wins_over_everything(self):
        with self._env(WEBSHARE_API_KEY="K", PROXY_LIST="a:1:u:p"), \
             patch.object(ProxyRotator, "from_file", return_value=ProxyRotator(["f"])) as ff, \
             patch.object(ProxyRotator, "from_webshare") as ws:
            rotator = ProxyRotator.from_config("proxies.txt")
        ff.assert_called_once_with("proxies.txt")
        ws.assert_not_called()
        self.assertEqual(rotator._proxies, ["f"])

    def test_webshare_used_when_api_key_set(self):
        with self._env(WEBSHARE_API_KEY="K", PROXY_LIST="a:1:u:p"), \
             patch.object(ProxyRotator, "from_webshare", return_value=ProxyRotator(["w"])) as ws:
            rotator = ProxyRotator.from_config()
        ws.assert_called_once_with("K")
        self.assertEqual(rotator._proxies, ["w"])

    def test_falls_back_to_proxy_list_when_webshare_raises(self):
        with self._env(WEBSHARE_API_KEY="K", PROXY_LIST="a:1:u:p"), \
             patch.object(ProxyRotator, "from_webshare", side_effect=RuntimeError("down")):
            rotator = ProxyRotator.from_config()
        self.assertEqual(rotator._proxies, ["http://u:p@a:1"])

    def test_falls_back_to_proxy_list_when_webshare_returns_nothing(self):
        with self._env(WEBSHARE_API_KEY="K", PROXY_LIST="a:1:u:p"), \
             patch.object(ProxyRotator, "from_webshare", return_value=ProxyRotator([])):
            rotator = ProxyRotator.from_config()
        self.assertEqual(rotator._proxies, ["http://u:p@a:1"])

    def test_webshare_failure_log_never_contains_the_api_key(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with self._env(WEBSHARE_API_KEY="SECRETKEY123"), \
             patch.object(ProxyRotator, "from_webshare", side_effect=RuntimeError("SECRETKEY123 leaked")), \
             redirect_stdout(buf):
            ProxyRotator.from_config()
        self.assertNotIn("SECRETKEY123", buf.getvalue())

    def test_no_sources_means_empty_rotator(self):
        with self._env():
            rotator = ProxyRotator.from_config()
        self.assertEqual(rotator._proxies, [])

    def test_only_proxy_list_set_uses_it(self):
        with self._env(PROXY_LIST="a:1:u:p,b:2:u:p"):
            rotator = ProxyRotator.from_config()
        self.assertEqual(len(rotator._proxies), 2)


if __name__ == "__main__":
    unittest.main()
