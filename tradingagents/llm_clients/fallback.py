"""Client-side model fallback wrapper for providers without native fallback support."""

import json
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

logger = logging.getLogger(__name__)

# Errors that should trigger fallback to next model
_FALLBACK_ERROR_MARKERS = (
    "rate_limit",
    "rate limit",
    "429",
    "quota",
    "capacity",
    "overloaded",
    "unavailable",
    "model_not_found",
    "model not found",
    "does not exist",
    "not supported",
    "no longer available",
    "deprecated",
)


def _is_fallback_error(exc: Exception) -> bool:
    """Check if an exception should trigger model fallback."""
    message = str(exc).lower()
    return any(marker in message for marker in _FALLBACK_ERROR_MARKERS)


def _parse_fallback_models(raw: str | list | dict | None) -> list[str]:
    """Parse fallback models from various config formats.

    Accepts:
    - Comma-separated string: "model-a,model-b,model-c"
    - JSON list string: '["model-a","model-b"]'
    - Python list: ["model-a", "model-b"]
    - Dict (provider-specific): {"openrouter": "m1,m2", "nvidia": "m3"}
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(m).strip() for m in raw if str(m).strip()]
    if isinstance(raw, dict):
        # Dict is handled at a higher level (per-provider config)
        return []
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        # Try JSON first
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(m).strip() for m in parsed if str(m).strip()]
            except json.JSONDecodeError:
                pass
        # Fall back to comma-separated
        return [m.strip() for m in raw.split(",") if m.strip()]
    return []


def _get_provider_fallbacks(
    tier_fallbacks: str | list | dict | None,
    provider_fallbacks: dict | str | None,
    provider: str,
) -> list[str]:
    """Resolve fallback chain for a specific provider.

    Priority:
    1. Provider-specific override (from *_by_provider config)
    2. Tier-level fallback (from *_fallback_models config)

    Accepts provider_fallbacks as dict or JSON string.
    The dict maps fallback_provider -> model list, allowing cross-provider fallbacks
    (e.g., primary=NVIDIA, fallbacks via OpenRouter).
    """
    import json

    # Parse JSON string if needed
    if isinstance(provider_fallbacks, str):
        try:
            provider_fallbacks = json.loads(provider_fallbacks)
        except json.JSONDecodeError:
            provider_fallbacks = None

    # Check provider-specific override first
    # provider_fallbacks maps fallback_provider -> model list
    # We try each fallback_provider in order until one has models
    if provider_fallbacks and isinstance(provider_fallbacks, dict):
        for _fallback_provider, provider_raw in provider_fallbacks.items():
            if provider_raw:
                return _parse_fallback_models(provider_raw)

    # Fall back to tier-level
    return _parse_fallback_models(tier_fallbacks)


class FallbackChatModel(BaseChatModel):
    """Wrapper that tries models in order on fallback-triggering errors.

    This enables fallback chains for ANY provider, not just OpenRouter.
    Primary model is tried first; on rate-limit/unavailable errors, falls back
    to the next model in the chain.
    """

    model_config = {"arbitrary_types_allowed": True}

    _primary_model: BaseChatModel
    _fallback_models: list[BaseChatModel]
    _fallback_model_names: list[str]

    def __init__(
        self,
        primary_model: BaseChatModel,
        fallback_models: list[BaseChatModel],
        fallback_model_names: list[str],
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        object.__setattr__(self, "_primary_model", primary_model)
        object.__setattr__(self, "_fallback_models", fallback_models)
        object.__setattr__(self, "_fallback_model_names", fallback_model_names)

    @property
    def primary_model(self) -> BaseChatModel:
        return self._primary_model

    @property
    def fallback_models(self) -> list[BaseChatModel]:
        return self._fallback_models

    @property
    def fallback_model_names(self) -> list[str]:
        return self._fallback_model_names

    @property
    def _llm_type(self) -> str:
        return "fallback_chat_model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Try primary, then fallbacks on retryable errors."""
        models_to_try = [self.primary_model] + self.fallback_models
        model_names = [getattr(self.primary_model, "model_name", "primary")] + self.fallback_model_names

        last_exception = None
        for i, (model, name) in enumerate(zip(models_to_try, model_names, strict=False)):
            try:
                if i > 0:
                    logger.warning(
                        "Falling back to model %s (%d/%d) after error: %s",
                        name,
                        i,
                        len(models_to_try) - 1,
                        last_exception,
                    )
                return model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                last_exception = exc
                if i == len(models_to_try) - 1:
                    # Last model, re-raise
                    raise
                if not _is_fallback_error(exc):
                    # Non-retryable error, don't fall back
                    raise
                # Retryable error, continue to next model
                continue

        # Should not reach here, but just in case
        raise last_exception  # type: ignore

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async version with fallback support."""
        models_to_try = [self.primary_model] + self.fallback_models
        model_names = [getattr(self.primary_model, "model_name", "primary")] + self.fallback_model_names

        last_exception = None
        for i, (model, name) in enumerate(zip(models_to_try, model_names, strict=False)):
            try:
                if i > 0:
                    logger.warning(
                        "Falling back to model %s (%d/%d) after error: %s",
                        name,
                        i,
                        len(models_to_try) - 1,
                        last_exception,
                    )
                return await model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as exc:
                last_exception = exc
                if i == len(models_to_try) - 1:
                    raise
                if not _is_fallback_error(exc):
                    raise
                continue

        raise last_exception  # type: ignore

    # Delegate other methods to primary model
    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to primary model."""
        # Use object.__getattribute__ to avoid recursion on private attrs
        primary = object.__getattribute__(self, "_primary_model")
        return getattr(primary, name)


def create_fallback_chain(
    primary_model: BaseChatModel,
    fallback_model_factory: callable,
    fallback_model_names: list[str],
) -> BaseChatModel:
    """Create a fallback chain wrapper.

    Args:
        primary_model: The primary LLM instance
        fallback_model_factory: Callable(model_name) -> BaseChatModel to create fallback instances
        fallback_model_names: List of fallback model names/IDs in priority order

    Returns:
        A ChatModel that tries primary, then fallbacks on retryable errors.
    """
    if not fallback_model_names:
        return primary_model

    fallback_models = [fallback_model_factory(name) for name in fallback_model_names]
    return FallbackChatModel(primary_model, fallback_models, fallback_model_names)
