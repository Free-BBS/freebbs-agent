import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import httpx

from freebbs_agent.server_settings import (
    SETTINGS_UNAVAILABLE_MESSAGE,
    ServerSettingsError,
    ServerSettingsProvider,
)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def settings_payload(*, revision="1", api_key="super-secret-key"):
    return {
        "apiKey": api_key,
        "baseUrl": "https://models.example.test/v1",
        "model": "test-model",
        "courseMaterialsRoot": "/srv/free-bbs/course-materials",
        "revision": revision,
    }


def mock_client_factory(handler):
    def factory():
        return httpx.Client(
            base_url="http://localhost",
            transport=httpx.MockTransport(handler),
            timeout=1,
            trust_env=False,
        )

    return factory


class ServerSettingsProviderTest(unittest.TestCase):
    def test_fetches_expected_contract_and_hides_api_key_from_repr(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=settings_payload(), request=request)

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            client_factory=mock_client_factory(handler),
        )

        snapshot = provider.get_snapshot()

        self.assertEqual(snapshot.api_key, "super-secret-key")
        self.assertEqual(snapshot.revision, "1")
        self.assertNotIn("super-secret-key", repr(snapshot))
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/internal/v1/agent-config")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer service-token")
        self.assertEqual(requests[0].headers["Accept"], "application/json")

    def test_default_client_uses_unix_socket_short_timeout_and_ignores_proxies(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.return_value = httpx.Response(200, json=settings_payload())

        with (
            patch("freebbs_agent.server_settings.httpx.HTTPTransport") as transport,
            patch("freebbs_agent.server_settings.httpx.Client", return_value=client) as client_class,
        ):
            provider = ServerSettingsProvider(
                "/run/free-bbs/agent-config.sock",
                "service-token",
                timeout_seconds=1.25,
            )
            provider.get_snapshot()

        transport.assert_called_once_with(uds="/run/free-bbs/agent-config.sock")
        client_kwargs = client_class.call_args.kwargs
        self.assertEqual(client_kwargs["base_url"], "http://localhost")
        self.assertFalse(client_kwargs["trust_env"])
        self.assertEqual(client_kwargs["timeout"].connect, 1.25)

    def test_allows_an_empty_course_materials_root(self):
        payload = settings_payload()
        payload["courseMaterialsRoot"] = ""

        def handler(request):
            return httpx.Response(200, json=payload, request=request)

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            client_factory=mock_client_factory(handler),
        )

        self.assertEqual(provider.get_snapshot().course_materials_root, "")

    def test_caches_within_ttl_and_refreshes_after_ttl(self):
        clock = FakeClock()
        revisions = iter(["1", "2"])
        calls = []

        def handler(request):
            revision = next(revisions)
            calls.append(revision)
            return httpx.Response(200, json=settings_payload(revision=revision), request=request)

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            cache_ttl_seconds=30,
            stale_ttl_seconds=300,
            clock=clock,
            client_factory=mock_client_factory(handler),
        )

        self.assertEqual(provider.get_snapshot().revision, "1")
        clock.advance(29)
        self.assertEqual(provider.get_snapshot().revision, "1")
        self.assertEqual(calls, ["1"])
        clock.advance(2)
        self.assertEqual(provider.get_snapshot().revision, "2")
        self.assertEqual(calls, ["1", "2"])

    def test_uses_bounded_stale_snapshot_for_transient_failures(self):
        clock = FakeClock()
        should_fail = False

        def handler(request):
            if should_fail:
                raise httpx.ConnectError("transport details must stay private", request=request)
            return httpx.Response(200, json=settings_payload(), request=request)

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            cache_ttl_seconds=30,
            stale_ttl_seconds=300,
            clock=clock,
            client_factory=mock_client_factory(handler),
        )

        cached = provider.get_snapshot()
        should_fail = True
        clock.advance(31)
        self.assertIs(provider.get_snapshot(), cached)

        clock.advance(300)
        with self.assertRaisesRegex(ServerSettingsError, f"^{SETTINGS_UNAVAILABLE_MESSAGE}$"):
            provider.get_snapshot()

    def test_auth_failure_fails_closed_and_clears_stale_cache(self):
        clock = FakeClock()
        responses = iter(
            [
                (200, settings_payload()),
                (403, {"error": {"code": "forbidden"}}),
                (503, {"error": {"code": "temporary_failure"}}),
            ]
        )

        def handler(request):
            status, payload = next(responses)
            return httpx.Response(status, json=payload, request=request)

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            cache_ttl_seconds=30,
            stale_ttl_seconds=300,
            clock=clock,
            client_factory=mock_client_factory(handler),
        )

        provider.get_snapshot()
        clock.advance(31)
        with self.assertRaises(ServerSettingsError):
            provider.get_snapshot()
        with self.assertRaises(ServerSettingsError):
            provider.get_snapshot()

    def test_server_reported_missing_configuration_clears_cache(self):
        clock = FakeClock()
        responses = iter(
            [
                (200, settings_payload()),
                (503, {"error": {"code": "agent_config_missing"}}),
            ]
        )

        def handler(request):
            status, payload = next(responses)
            return httpx.Response(status, json=payload, request=request)

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            cache_ttl_seconds=30,
            stale_ttl_seconds=300,
            clock=clock,
            client_factory=mock_client_factory(handler),
        )

        provider.get_snapshot()
        clock.advance(31)
        with self.assertRaises(ServerSettingsError):
            provider.get_snapshot()

    def test_malformed_success_response_fails_closed_without_leaking_body(self):
        leaked_key = "do-not-leak-this-key"

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "apiKey": leaked_key,
                    "baseUrl": "not-a-url",
                    "model": "test-model",
                    "courseMaterialsRoot": "/srv/materials",
                    "revision": "1",
                },
                request=request,
            )

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            client_factory=mock_client_factory(handler),
        )

        with self.assertRaises(ServerSettingsError) as raised:
            provider.get_snapshot()
        self.assertEqual(str(raised.exception), SETTINGS_UNAVAILABLE_MESSAGE)
        self.assertNotIn(leaked_key, repr(raised.exception))

    def test_concurrent_cold_reads_share_one_refresh(self):
        calls = 0
        calls_lock = threading.Lock()

        def handler(request):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.02)
            return httpx.Response(200, json=settings_payload(), request=request)

        provider = ServerSettingsProvider(
            "/run/free-bbs/agent-config.sock",
            "service-token",
            client_factory=mock_client_factory(handler),
        )

        with ThreadPoolExecutor(max_workers=8) as executor:
            snapshots = list(executor.map(lambda _: provider.get_snapshot(), range(8)))

        self.assertEqual(calls, 1)
        self.assertTrue(all(snapshot is snapshots[0] for snapshot in snapshots))

    def test_validates_transport_and_cache_configuration(self):
        with self.assertRaises(ValueError):
            ServerSettingsProvider("relative.sock", "token")
        with self.assertRaises(ValueError):
            ServerSettingsProvider("/run/free-bbs/settings.sock", "")
        with self.assertRaises(ValueError):
            ServerSettingsProvider(
                "/run/free-bbs/settings.sock",
                "token",
                cache_ttl_seconds=60,
                stale_ttl_seconds=30,
            )


if __name__ == "__main__":
    unittest.main()
