# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Unit tests for the LLM helpers in ``plane.app.views.external.base``.

Covers the bring-your-own-provider behavior:

- ``LLM_BASE_URL`` is read and forwarded to the OpenAI-compatible client.
- Any model name is accepted (the provider model lists are UI hints only).
- Model names are passed verbatim (no provider-specific prefix rewriting).
- Missing/unsupported configuration degrades to ``(None, None, None, None)``.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from plane.app.views.external.base import get_llm_config, get_llm_response


def _completion(text="generated text"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _client(completion=None, error=None):
    """OpenAI-client stand-in that records ``create()`` kwargs on itself."""
    client = SimpleNamespace()
    client.create_kwargs = {}

    def create(**kwargs):
        client.create_kwargs.update(kwargs)
        if error is not None:
            raise error
        return completion if completion is not None else _completion()

    client.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
    return client


@pytest.mark.unit
class TestGetLLMConfig:
    def test_returns_all_values_when_fully_configured(self):
        with patch(
            "plane.app.views.external.base.get_configuration_value",
            return_value=("sk-test", "openai", "gpt-4o-mini", "https://gw/v1"),
        ):
            api_key, model, provider, base_url = get_llm_config()

        assert api_key == "sk-test"
        assert model == "gpt-4o-mini"
        assert provider == "openai"
        assert base_url == "https://gw/v1"

    def test_base_url_is_none_when_not_configured(self):
        with patch(
            "plane.app.views.external.base.get_configuration_value",
            return_value=("sk-test", "openai", "gpt-4o-mini", None),
        ):
            _, _, _, base_url = get_llm_config()

        assert base_url is None

    def test_falls_back_to_provider_default_model(self):
        with patch(
            "plane.app.views.external.base.get_configuration_value",
            return_value=("sk-test", "openai", None, None),
        ):
            _, model, _, _ = get_llm_config()

        assert model == "gpt-4o-mini"

    def test_accepts_model_names_outside_the_provider_list(self):
        # Bring-your-own-provider: gateways serve custom model names that the
        # hardcoded provider lists cannot know about.
        with patch(
            "plane.app.views.external.base.get_configuration_value",
            return_value=("sk-test", "openai", "deepseek-chat", None),
        ):
            api_key, model, provider, _ = get_llm_config()

        assert api_key == "sk-test"
        assert model == "deepseek-chat"
        assert provider == "openai"

    def test_unsupported_provider_returns_none(self):
        with patch(
            "plane.app.views.external.base.get_configuration_value",
            return_value=("sk-test", "skynet", "m", None),
        ):
            assert get_llm_config() == (None, None, None, None)

    def test_missing_api_key_returns_none(self):
        with patch(
            "plane.app.views.external.base.get_configuration_value",
            return_value=(None, "openai", "gpt-4o-mini", None),
        ):
            assert get_llm_config() == (None, None, None, None)


@pytest.mark.unit
class TestGetLLMResponse:
    def test_forwards_base_url_to_client(self):
        with (
            patch(
                "plane.app.views.external.base.get_configuration_value",
                return_value=("sk-test", "openai", "deepseek-chat", "https://gw/v1"),
            ),
            patch("plane.app.views.external.base.OpenAI", return_value=_client()) as openai_cls,
        ):
            text, error = get_llm_response(
                "summarize", "the issue", "sk-test", "deepseek-chat", "openai", "https://gw/v1"
            )

        openai_cls.assert_called_once_with(api_key="sk-test", base_url="https://gw/v1")
        assert text == "generated text"
        assert error is None

    def test_openai_default_endpoint_when_base_url_missing(self):
        with (
            patch(
                "plane.app.views.external.base.get_configuration_value",
                return_value=("sk-test", "openai", "gpt-4o-mini", None),
            ),
            patch("plane.app.views.external.base.OpenAI", return_value=_client()) as openai_cls,
        ):
            text, error = get_llm_response("summarize", "the issue", "sk-test", "gpt-4o-mini", "openai", None)

        openai_cls.assert_called_once_with(api_key="sk-test", base_url=None)
        assert text == "generated text"
        assert error is None

    def test_model_name_is_passed_verbatim_for_gemini(self):
        # Regression guard: the legacy ``gemini/`` prefix rewriting is gone.
        client = _client()
        with patch("plane.app.views.external.base.OpenAI", return_value=client):
            get_llm_response("summarize", "the issue", "sk-test", "gemini-2.0-flash", "gemini", "https://gw/v1")

        assert client.create_kwargs["model"] == "gemini-2.0-flash"

    def test_generic_error_returns_error_message(self):
        with patch("plane.app.views.external.base.OpenAI", return_value=_client(error=Exception("boom"))):
            text, error = get_llm_response("summarize", "the issue", "sk-test", "gpt-4o-mini", "openai", None)

        assert text is None
        assert error == "Error occurred while generating response from openai"

    def test_sends_single_user_message(self):
        client = _client()
        with patch("plane.app.views.external.base.OpenAI", return_value=client):
            get_llm_response("my task", "my prompt", "sk-test", "gpt-4o-mini", "openai", None)

        assert client.create_kwargs["messages"] == [{"role": "user", "content": "my task\nmy prompt"}]
