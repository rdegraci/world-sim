"""LLM provider factory."""

from __future__ import annotations

import os

from world_sim.config import ConfigError, Settings
from world_sim.llm.anthropic_adapter import (
    DEFAULT_ANTHROPIC_MODEL,
    AnthropicAdapter,
)
from world_sim.llm.base import LLMAdapter
from world_sim.llm.fake_adapter import FakeAdapter
from world_sim.llm.grok_adapter import DEFAULT_GROK_MODEL, GrokAdapter
from world_sim.llm.openai_adapter import DEFAULT_OPENAI_MODEL, OpenAIAdapter
from world_sim.utils.logger import get_logger


def create_llm_adapter(settings: Settings) -> LLMAdapter:
    """Create the configured provider adapter.

    Set WORLD_SIM_LLM=fake to force the offline FakeAdapter (useful in tests).
    """
    logger = get_logger("llm.factory")
    override = os.environ.get("WORLD_SIM_LLM", "").strip().lower()
    if override == "fake":
        logger.info("Using FakeAdapter via WORLD_SIM_LLM=fake")
        return FakeAdapter()

    provider = settings.provider.lower()
    if provider == "grok":
        model = str(settings.raw_config.get("grok_model", DEFAULT_GROK_MODEL))
        logger.info("Selecting GrokAdapter model=%s", model)
        return GrokAdapter(api_key=settings.grok_api_key, model=model)
    if provider == "openai":
        if not settings.openai_api_key:
            raise ConfigError(
                "provider=openai requires OPENAI_API_KEY in the app .env file."
            )
        model = str(settings.raw_config.get("openai_model", DEFAULT_OPENAI_MODEL))
        logger.info("Selecting OpenAIAdapter model=%s", model)
        return OpenAIAdapter(api_key=settings.openai_api_key, model=model)
    if provider in {"anthropic", "claude"}:
        if not settings.anthropic_api_key:
            raise ConfigError(
                "provider=anthropic requires ANTHROPIC_API_KEY in the app .env file."
            )
        model = str(
            settings.raw_config.get("anthropic_model", DEFAULT_ANTHROPIC_MODEL)
        )
        logger.info("Selecting AnthropicAdapter model=%s", model)
        return AnthropicAdapter(api_key=settings.anthropic_api_key, model=model)

    raise ConfigError(
        f"Unknown provider '{settings.provider}'. "
        "Supported providers: grok, openai, anthropic."
    )
