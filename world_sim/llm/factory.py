"""LLM provider factory."""

from __future__ import annotations

import os

from world_sim.config import Settings
from world_sim.llm.base import LLMAdapter
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.llm.grok_adapter import DEFAULT_GROK_MODEL, GrokAdapter


def create_llm_adapter(settings: Settings) -> LLMAdapter:
    """Create the configured provider adapter.

    Set WORLD_SIM_LLM=fake to force the offline FakeAdapter (useful in tests).
    """
    override = os.environ.get("WORLD_SIM_LLM", "").strip().lower()
    if override == "fake":
        return FakeAdapter()

    provider = settings.provider.lower()
    if provider == "grok":
        model = str(settings.raw_config.get("grok_model", DEFAULT_GROK_MODEL))
        return GrokAdapter(api_key=settings.grok_api_key, model=model)

    # Slice 3 only requires Grok. Unknown providers fall back to fake for safety
    # in local development until Slice 5 expands adapters.
    return FakeAdapter()
