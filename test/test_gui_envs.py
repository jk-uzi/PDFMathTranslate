"""Tests for the Gradio env input slots and the link-download SSRF guard.

These tests exercise the module-level pure helpers of ``pdf2zh.gui``
(``build_env_specs`` / ``assemble_envs`` / ``_validate_remote_url``) plus the
redirect handling of ``download_with_limit``. No real network access is made:
DNS resolution and HTTP requests are mocked.
"""

import ipaddress
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Ensure the project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr  # noqa: E402

import pdf2zh.gui  # noqa: E402
from pdf2zh.config import ConfigManager  # noqa: E402
from pdf2zh.gui import (  # noqa: E402
    MAX_ENV_FIELDS,
    _validate_remote_url,
    assemble_envs,
    build_env_specs,
    download_with_limit,
    service_map,
)
from pdf2zh.gui import demo as gui_demo  # noqa: E402

# A public address used to keep DNS resolution offline in tests.
PUBLIC_ADDRINFO = [("93.184.216.34", 0, 0, "", ("93.184.216.34", 443))]
LOOPBACK_ADDRINFO = [("127.0.0.1", 0, 0, "", ("127.0.0.1", 0))]


def _offline_resolver(host, port=None, *args, **kwargs):
    """Stand-in for socket.getaddrinfo that never touches the network.

    Literal IP addresses resolve to themselves (as the real resolver does),
    ``localhost`` resolves to loopback, any other host name resolves to a
    public address.
    """
    host = str(host)
    if host.lower() in ("localhost", "localhost.localdomain"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 0))]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return PUBLIC_ADDRINFO
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (str(ip), port or 0))]


def _fake_response(status=200, headers=None, content=b"%PDF-1.4"):
    """Build a MagicMock good enough to stand in for a requests.Response."""
    response = mock.MagicMock()
    response.status_code = status
    response.headers = headers or {}
    response.is_redirect = status in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status in (301, 308)
    response.iter_content.return_value = [content]
    response.__enter__.return_value = response
    return response


class TestModuleIdentity(unittest.TestCase):
    """Guard against silently testing a different checkout's gui.py."""

    def test_gui_module_comes_from_this_project(self):
        imported = Path(pdf2zh.gui.__file__).resolve()
        expected = (PROJECT_ROOT / "pdf2zh" / "gui.py").resolve()
        self.assertEqual(imported, expected)


class TestBuildEnvSpecs(unittest.TestCase):
    """AC-1 / AC-2 / AC-2b: every service gets a full, collision-free slot list."""

    def setUp(self):
        # Keep the tests hermetic: never read/write the user's real config file.
        self._env_lookup = mock.patch.object(
            ConfigManager,
            "get_env_by_translatername",
            side_effect=lambda translator, key, default=None: default,
        )
        self._env_lookup.start()
        self.addCleanup(self._env_lookup.stop)

    def test_ac1_slot_count_is_dynamic_and_large_enough(self):
        self.assertGreaterEqual(MAX_ENV_FIELDS, 6)
        for name, translator in service_map.items():
            with self.subTest(service=name):
                specs = build_env_specs(translator, MAX_ENV_FIELDS)
                self.assertEqual(len(specs), MAX_ENV_FIELDS)

    def test_ac1_never_raises_when_fewer_slots_than_keys(self):
        # A too-small max_fields must truncate, never raise IndexError.
        translator = service_map["OpenAI"]
        specs = build_env_specs(translator, 2)
        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0]["label"], "OPENAI_BASE_URL")
        self.assertEqual(specs[1]["label"], "OPENAI_API_KEY")

    def test_ac2_openai_exposes_all_six_fields(self):
        translator = service_map["OpenAI"]
        specs = build_env_specs(translator, MAX_ENV_FIELDS)
        visible = [spec for spec in specs if spec["visible"]]
        self.assertEqual(len(visible), len(translator.envs))
        self.assertEqual(len(visible), 6)
        self.assertEqual(visible[5]["label"], "OPENAI_MAX_TOKENS")
        self.assertEqual(
            [spec["label"] for spec in visible], list(translator.envs.keys())
        )

    def test_ac2_openai_liked_exposes_all_six_fields(self):
        translator = service_map["OpenAI-liked"]
        specs = build_env_specs(translator, MAX_ENV_FIELDS)
        visible = [spec for spec in specs if spec["visible"]]
        self.assertEqual(len(visible), len(translator.envs))
        self.assertEqual(len(visible), 6)
        self.assertEqual(visible[5]["label"], "OPENAILIKED_MAX_TOKENS")
        self.assertEqual(
            [spec["label"] for spec in visible], list(translator.envs.keys())
        )

    def test_ac2b_four_key_services_are_not_clobbered(self):
        for name, last_key in (
            ("AzureOpenAI", "AZURE_OPENAI_API_VERSION"),
            ("Grok", "GROK_STREAM"),
        ):
            with self.subTest(service=name):
                translator = service_map[name]
                specs = build_env_specs(translator, MAX_ENV_FIELDS)
                visible = [spec for spec in specs if spec["visible"]]
                self.assertEqual(len(translator.envs), 4)
                self.assertEqual(len(visible), 4)
                self.assertEqual(visible[3]["label"], last_key)
                self.assertEqual(
                    [spec["label"] for spec in visible], list(translator.envs.keys())
                )

    def test_slots_beyond_key_count_are_hidden_and_empty(self):
        translator = service_map["Google"]  # no env keys at all
        specs = build_env_specs(translator, MAX_ENV_FIELDS)
        self.assertTrue(all(not spec["visible"] for spec in specs))
        self.assertTrue(all(spec["label"] == "" for spec in specs))

    def test_hidden_details_masks_api_key_and_hides_non_model_values(self):
        translator = service_map["OpenAI"]

        def fake_lookup(translater, key, default=None):
            if key == "OPENAI_API_KEY":
                return "sk-secret"
            return default

        with mock.patch.object(
            ConfigManager, "get_env_by_translatername", side_effect=fake_lookup
        ):
            specs = build_env_specs(translator, MAX_ENV_FIELDS, hidden=True)
        by_label = {spec["label"]: spec for spec in specs if spec["label"]}
        self.assertEqual(by_label["OPENAI_API_KEY"]["value"], "***")
        self.assertFalse(by_label["OPENAI_API_KEY"]["visible"])
        # MODEL values stay visible so the user can still pick a model.
        self.assertTrue(by_label["OPENAI_MODEL"]["visible"])
        # Other non-empty values are hidden from the UI.
        self.assertFalse(by_label["OPENAI_BASE_URL"]["visible"])


class TestAssembleEnvs(unittest.TestCase):
    """The positional widget values must map back onto the env keys."""

    def test_positional_values_map_to_env_keys(self):
        translator = service_map["OpenAI"]
        values = [
            "https://example.com/v1",
            "sk-test",
            "gpt-4o-mini",
            "false",
            "",
            "128",
        ]
        envs = assemble_envs(translator, values)
        self.assertEqual(envs, dict(zip(translator.envs.keys(), values)))

    def test_masked_api_key_is_restored_from_config(self):
        translator = service_map["OpenAI"]
        values = ["https://example.com/v1", "***", "gpt-4o-mini", "true", "", "-1"]
        with mock.patch.object(
            ConfigManager, "get_env_by_translatername", return_value="real-key"
        ) as lookup:
            envs = assemble_envs(translator, values)
        self.assertEqual(envs["OPENAI_API_KEY"], "real-key")
        lookup.assert_called_once_with(translator, "OPENAI_API_KEY", None)

    def test_fewer_values_than_keys_does_not_raise(self):
        translator = service_map["OpenAI"]
        envs = assemble_envs(translator, ["only-base-url"])
        self.assertEqual(envs, {"OPENAI_BASE_URL": "only-base-url"})


class TestValidateRemoteUrl(unittest.TestCase):
    """AC-6: SSRF validation happens before any request is issued."""

    def test_rejects_non_http_and_internal_targets(self):
        bad_urls = [
            "file:///etc/passwd",
            "http://127.0.0.1:8000/x",
            "http://localhost:8000/x",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/x",
            "http://192.168.1.1/x",
            "ftp://example.com/x",
            # extra hardening
            "gopher://example.com/x",
            "example.com/x",
            "http://[::1]/x",
            "http://0.0.0.0/x",
        ]
        for url in bad_urls:
            with self.subTest(url=url), self.assertRaises(gr.Error):
                _validate_remote_url(url)

    def test_accepts_public_https_url(self):
        with mock.patch(
            "pdf2zh.gui.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO
        ) as resolver:
            _validate_remote_url("https://example.com/doc.pdf")
        resolver.assert_called_once_with("example.com", None)

    def test_rejects_public_hostname_resolving_to_private_address(self):
        mixed = PUBLIC_ADDRINFO + [("10.0.0.5", 0, 0, "", ("10.0.0.5", 443))]
        with mock.patch("pdf2zh.gui.socket.getaddrinfo", return_value=mixed):
            with self.assertRaises(gr.Error):
                _validate_remote_url("https://example.com/doc.pdf")


class TestDownloadWithLimit(unittest.TestCase):
    """The download path must validate before requesting, including redirects."""

    def test_rejects_private_url_without_any_request(self):
        with mock.patch("pdf2zh.gui.requests.get") as get:
            with self.assertRaises(gr.Error):
                download_with_limit("http://127.0.0.1:8000/x", Path("."), None)
            get.assert_not_called()

    def test_rejects_redirect_to_private_host_before_second_request(self):
        redirect = _fake_response(
            status=302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
        )
        with (
            mock.patch("pdf2zh.gui.socket.getaddrinfo", side_effect=_offline_resolver),
            mock.patch("pdf2zh.gui.requests.get", return_value=redirect) as get,
        ):
            with self.assertRaises(gr.Error):
                download_with_limit("https://example.com/doc.pdf", Path("."), None)
        # The private redirect target must never be requested.
        self.assertEqual(get.call_count, 1)

    def test_follows_public_redirect_and_saves_pdf(self):
        redirect = _fake_response(status=302, headers={"Location": "/real.pdf"})
        final = _fake_response(
            status=200,
            headers={"Content-Disposition": 'attachment; filename="doc.txt"'},
            content=b"%PDF-1.4 hello",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch(
                    "pdf2zh.gui.socket.getaddrinfo", side_effect=_offline_resolver
                ),
                mock.patch(
                    "pdf2zh.gui.requests.get", side_effect=[redirect, final]
                ) as get,
            ):
                saved = download_with_limit("https://example.com/doc", Path(tmp), None)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(saved.name, "doc.pdf")
            self.assertEqual(saved.suffix, ".pdf")
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_bytes(), b"%PDF-1.4 hello")

    def test_enforces_size_limit(self):
        final = _fake_response(status=200, content=b"x" * 2048)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch(
                    "pdf2zh.gui.socket.getaddrinfo", side_effect=_offline_resolver
                ),
                mock.patch("pdf2zh.gui.requests.get", return_value=final),
            ):
                with self.assertRaises(gr.Error):
                    download_with_limit("https://example.com/a.pdf", Path(tmp), 1024)

    def test_rejects_too_many_redirects(self):
        redirects = [
            _fake_response(status=302, headers={"Location": "https://example.com/next"})
            for _ in range(6)
        ]
        with (
            mock.patch("pdf2zh.gui.socket.getaddrinfo", side_effect=_offline_resolver),
            mock.patch("pdf2zh.gui.requests.get", side_effect=redirects) as get,
        ):
            with self.assertRaises(gr.Error):
                download_with_limit("https://example.com/a.pdf", Path("."), None)
        self.assertLessEqual(get.call_count, 6)


class TestGuiWiring(unittest.TestCase):
    """The service dropdown must drive exactly MAX_ENV_FIELDS + 1 outputs."""

    def _component(self, component_id):
        for component in gui_demo.config["components"]:
            if component["id"] == component_id:
                return component
        self.fail(f"component {component_id} not found")

    def _label(self, component_id):
        return self._component(component_id).get("props", {}).get("label")

    def _service_id(self):
        for component in gui_demo.config["components"]:
            if component.get("props", {}).get("label") == "Service":
                return component["id"]
        self.fail("Service dropdown not found")

    def _env_ids(self, component_ids):
        """Ids of the anonymous env textboxes among `component_ids`."""
        return [
            cid
            for cid in component_ids
            if self._component(cid)["type"] == "textbox" and self._label(cid) is None
        ]

    @staticmethod
    def _targets(dependency):
        return [tuple(target) for target in (dependency.get("targets") or [])]

    def test_service_select_outputs_match_on_select_service(self):
        service_id = self._service_id()
        dependency = next(
            (
                dep
                for dep in gui_demo.config["dependencies"]
                if self._targets(dep) == [(service_id, "select")]
            ),
            None,
        )
        self.assertIsNotNone(dependency, "Service select dependency not found")
        self.assertEqual(dependency["inputs"], [service_id])
        outputs = dependency["outputs"]
        # MAX_ENV_FIELDS env textboxes followed by the custom-prompt textbox.
        self.assertEqual(len(outputs), MAX_ENV_FIELDS + 1)
        self.assertEqual(len(self._env_ids(outputs)), MAX_ENV_FIELDS)
        self.assertEqual(self._label(outputs[-1]), "Custom Prompt for llm")

    def test_translate_click_inputs_contain_prompt_once_and_all_envs(self):
        dependency = next(
            (
                dep
                for dep in gui_demo.config["dependencies"]
                if any(
                    self._component(target[0])["type"] == "button"
                    and self._component(target[0]).get("props", {}).get("value")
                    == "Translate"
                    and target[1] == "click"
                    for target in self._targets(dep)
                )
            ),
            None,
        )
        self.assertIsNotNone(dependency, "Translate click dependency not found")
        inputs = dependency["inputs"]
        labels = [self._label(cid) for cid in inputs]
        # The prompt must appear exactly once (it used to be passed twice).
        self.assertEqual(labels.count("Custom Prompt for llm"), 1)
        self.assertEqual(len(self._env_ids(inputs)), MAX_ENV_FIELDS)


if __name__ == "__main__":
    unittest.main()
