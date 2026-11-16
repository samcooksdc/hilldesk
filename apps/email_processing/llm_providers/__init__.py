# SPDX-License-Identifier: Apache-2.0
"""
LLM Provider Factory and Registry.

This module provides the factory function for instantiating LLM providers
based on environment configuration. It supports multiple backends:

- bedrock: Amazon Bedrock (PRODUCTION - only approved provider)
- mock: Offline development mock provider
- anthropic_dev: [TEMPORARY] Direct Anthropic API for development testing

Usage:
    from apps.email_processing.llm_providers import get_llm_provider

    provider = get_llm_provider()
    output = provider.extract_candidates(bundle)   # bundle: schema.MessageBundle
"""

import logging
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseLLMProvider
from .schema import MessageBundle, RawModelOutput, validate_candidate_set

logger = logging.getLogger(__name__)

# Re-export base classes for convenience
__all__ = [
    'get_llm_provider',
    'BaseLLMProvider',
    'MessageBundle',
    'RawModelOutput',
    'validate_candidate_set',
]


def get_llm_provider() -> BaseLLMProvider:
    """
    Factory function to get the appropriate LLM provider.

    The provider is selected based on the LLM_PROVIDER Django setting.
    Defaults to 'mock' for safe offline development.

    Returns:
        An instance of BaseLLMProvider subclass

    Raises:
        ImproperlyConfigured: If the configured provider is unknown

    Supported Providers:
        - 'bedrock': Amazon Bedrock (production, only approved provider)
        - 'mock': Mock provider (offline development)
        - 'anthropic_dev': [TEMPORARY] Direct Anthropic API (development only)
    """
    provider_name = getattr(settings, 'LLM_PROVIDER', 'mock')

    logger.info(f"Initializing LLM provider: {provider_name}")

    if provider_name == 'bedrock':
        from .bedrock import BedrockProvider
        return BedrockProvider()

    elif provider_name == 'mock':
        from .mock import MockProvider
        return MockProvider()

    elif provider_name == 'anthropic_dev':
        # TEMPORARY: This provider is for development testing only
        # It MUST be removed before production deployment
        from .anthropic_dev import AnthropicDevProvider
        return AnthropicDevProvider()

    else:
        raise ImproperlyConfigured(
            f"Unknown LLM_PROVIDER: '{provider_name}'. "
            f"Valid options are: 'bedrock', 'mock', 'anthropic_dev'"
        )


def get_available_providers() -> list:
    """
    Return list of available provider names.

    Returns:
        List of valid provider name strings
    """
    return ['bedrock', 'mock', 'anthropic_dev']
