import asyncio

import pytest
from pydantic import BaseModel

from incident_llm import (
    LLMAuthError, LLMClient, LLMInvalidConfig, LLMMalformedResponse, LLMNotConfigured,
    LLMQuotaExhausted, LLMRateLimited, LLMTimeout, load_llm_config, parse_model_id,
)
from incident_llm.providers.gemini import map_gemini_error

SECRET = "super-secret-key-123"


class Out(BaseModel):
    answer: str


class ScriptedProvider:
    def __init__(self, steps):
        self.steps, self.calls = list(steps), 0

    async def generate_json(self, system_prompt, user_prompt, schema):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return await step()
        return step


def cfg(**env):
    base = {"LLM_MODEL": "gemini/gemini-2.5-flash", "LLM_API_KEY": SECRET}
    base.update(env)
    return load_llm_config(base)


async def no_sleep(_):
    return None


# ---- configuration ----
def test_default_model_when_unset():
    c = load_llm_config({"LLM_API_KEY": "k"})
    assert (c.provider, c.model) == ("gemini", "gemini-2.5-flash")


def test_provider_inferred_from_prefix():
    assert parse_model_id("gemini/gemini-2.5-pro") == ("gemini", "gemini-2.5-pro")


@pytest.mark.parametrize("bad", ["gemini-2.5-flash", "/x", "gemini/", "openai/gpt"])
def test_invalid_model_ids_rejected(bad):
    with pytest.raises(ValueError):
        parse_model_id(bad)


def test_invalid_model_yields_config_error_not_exception():
    c = load_llm_config({"LLM_MODEL": "nonsense", "LLM_API_KEY": "k"})
    assert not c.configured and c.config_error


def test_missing_key_not_configured():
    c = load_llm_config({"LLM_MODEL": "gemini/gemini-2.5-flash"})
    assert not c.configured
    assert LLMClient(c).status()["state"] == "not_configured"


def test_switching_model_and_key_needs_only_env():
    a = cfg(LLM_MODEL="gemini/model-a", LLM_API_KEY="k1")
    b = cfg(LLM_MODEL="gemini/model-b", LLM_API_KEY="k2")
    assert a.model == "model-a" and b.model == "model-b" and a.api_key != b.api_key


def test_secret_never_in_repr_or_status():
    c = cfg()
    client = LLMClient(c)
    assert SECRET not in repr(c) and SECRET not in str(c)
    assert SECRET not in str(client.status())


# ---- client behaviour ----
async def test_missing_key_raises_not_configured():
    client = LLMClient(load_llm_config({}), provider=ScriptedProvider([]))
    with pytest.raises(LLMNotConfigured):
        await client.generate_structured("s", "u", Out)


async def test_invalid_config_raises():
    client = LLMClient(load_llm_config({"LLM_MODEL": "x", "LLM_API_KEY": "k"}))
    with pytest.raises(LLMInvalidConfig):
        await client.generate_structured("s", "u", Out)


async def test_structured_output_validated_from_dict():
    client = LLMClient(cfg(), ScriptedProvider([{"answer": "hi"}]))
    assert (await client.generate_structured("s", "u", Out)).answer == "hi"


async def test_schema_mismatch_is_malformed_after_retries():
    p = ScriptedProvider([{"wrong": 1}] * 3)
    client = LLMClient(cfg(), p, sleep=no_sleep)
    with pytest.raises(LLMMalformedResponse):
        await client.generate_structured("s", "u", Out)
    assert p.calls == 3


async def test_rate_limit_retried_then_succeeds():
    p = ScriptedProvider([LLMRateLimited("x"), {"answer": "ok"}])
    client = LLMClient(cfg(), p, sleep=no_sleep)
    assert (await client.generate_structured("s", "u", Out)).answer == "ok"
    assert p.calls == 2


async def test_auth_error_not_retried():
    p = ScriptedProvider([LLMAuthError("bad key")])
    client = LLMClient(cfg(), p, sleep=no_sleep)
    with pytest.raises(LLMAuthError):
        await client.generate_structured("s", "u", Out)
    assert p.calls == 1


async def test_quota_exhausted_not_retried():
    p = ScriptedProvider([LLMQuotaExhausted("q")])
    with pytest.raises(LLMQuotaExhausted):
        await LLMClient(cfg(), p, sleep=no_sleep).generate_structured("s", "u", Out)
    assert p.calls == 1


async def test_timeout_raises_llm_timeout():
    async def slow():
        await asyncio.sleep(1)

    client = LLMClient(cfg(LLM_TIMEOUT_SECONDS="0.01", LLM_MAX_RETRIES="0"), ScriptedProvider([slow]))
    with pytest.raises(LLMTimeout):
        await client.generate_structured("s", "u", Out)


async def test_retries_exhausted_raises_last_error():
    p = ScriptedProvider([LLMRateLimited("x")] * 3)
    with pytest.raises(LLMRateLimited):
        await LLMClient(cfg(), p, sleep=no_sleep).generate_structured("s", "u", Out)
    assert p.calls == 3


# ---- gemini error mapping ----
@pytest.mark.parametrize("code,msg,exc", [
    (401, "x", LLMAuthError), (403, "x", LLMAuthError),
    (400, "API key not valid. Please pass a valid API key.", LLMAuthError),
    (404, "models/foo is not found", __import__("incident_llm").LLMModelUnavailable),
    (429, "Quota exceeded for requests per day", LLMQuotaExhausted),
    (429, "Resource exhausted", LLMRateLimited),
    (503, "overloaded", __import__("incident_llm").LLMTransientError),
])
def test_gemini_error_mapping(code, msg, exc):
    assert isinstance(map_gemini_error(code, msg), exc)
