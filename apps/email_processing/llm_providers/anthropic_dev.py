# SPDX-License-Identifier: Apache-2.0
"""
============================================================
    TEMPORARY DEVELOPMENT PROVIDER - DO NOT USE IN PRODUCTION
============================================================

This module provides direct Anthropic API access for local LLM testing
during development. It MUST be removed or disabled before production
deployment.

REMOVAL CHECKLIST:
- [ ] Delete this file (email_processing/llm_providers/anthropic_dev.py)
- [ ] Remove 'anthropic_dev' case from llm_providers/__init__.py
- [ ] Remove 'anthropic' from requirements.txt
- [ ] Ensure LLM_PROVIDER is set to 'bedrock' in production
- [ ] Run production deployment checklist

PRODUCTION: This provider violates the production requirements (no third-party
SaaS LLM APIs). It exists solely for development convenience when testing
actual LLM extraction quality without Bedrock access.

Usage:
    export LLM_PROVIDER=anthropic_dev
    export ANTHROPIC_API_KEY=sk-ant-...
    python manage.py runserver
"""

import json
import logging
import os
import warnings

from django.conf import settings

from .base import BaseLLMProvider, DraftGenerationResult
from .schema import (
    EXTRACTION_SYSTEM_PROMPT, EXTRACTION_TOOL_NAME, MessageBundle,
    RawModelOutput, build_extraction_tool, build_extraction_user_content,
)

logger = logging.getLogger(__name__)


# ============================================================
#     TEMPORARY - REMOVE BEFORE PRODUCTION DEPLOYMENT
# ============================================================


class AnthropicDevProvider(BaseLLMProvider):
    """
    TEMPORARY: Direct Anthropic API provider for development testing.

    WARNING: This class is NOT approved for production and must be removed before
    production deployment. Use only for local testing of LLM extraction
    quality when you don't have access to Amazon Bedrock.

    For offline development without API access, use LLM_PROVIDER=mock instead.
    For production, use LLM_PROVIDER=bedrock.
    """

    def __init__(self):
        """
        Initialize the Anthropic development provider.

        Raises:
            ValueError: If ANTHROPIC_API_KEY is not set
            ImportError: If anthropic package is not installed
        """
        # Emit prominent warning at initialization
        warnings.warn(
            "\n" + "=" * 70 + "\n"
            "    TEMPORARY DEVELOPMENT LLM PROVIDER ACTIVE\n"
            "    Using direct Anthropic API - NOT FOR PRODUCTION\n"
            "\n"
            "    This provider must be removed before production deployment.\n"
            "    For production, set LLM_PROVIDER=bedrock\n"
            "=" * 70 + "\n",
            UserWarning,
            stacklevel=2
        )

        # Get API key from environment
        self.api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is required for the "
                "anthropic_dev provider. For offline development without an API key, "
                "use LLM_PROVIDER=mock instead."
            )

        # Get model from settings or use default
        self.model = getattr(
            settings,
            'ANTHROPIC_DEV_MODEL',
            'claude-3-haiku-20240307'
        )

        # Import and initialize the Anthropic client
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for the anthropic_dev provider. "
                "Install it with: pip install anthropic\n"
                "Note: This is a development-only dependency and should NOT be "
                "included in production requirements."
            )

        logger.warning(
            "=" * 70 + "\n"
            "AnthropicDevProvider initialized - NOT FOR PRODUCTION\n"
            f"Model: {self.model}\n"
            "=" * 70
        )


    def extract_candidates(self, bundle: MessageBundle) -> RawModelOutput:
        """
        The single extraction call via the Anthropic API: one
        messages.create with a FORCED tool-use definition built from the
        candidate-set schema. Same contract as the Bedrock provider.
        """
        content = []
        for img in bundle.image_blocks:
            ctype = (img.get('content_type') or '').lower()
            block_type = 'document' if ctype == 'application/pdf' else 'image'
            content.append({
                'type': block_type,
                'source': {
                    'type': 'base64',
                    'media_type': ctype,
                    'data': img.get('data_b64', ''),
                },
            })
        content.append({'type': 'text', 'text': build_extraction_user_content(bundle)})

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': content}],
                tools=[build_extraction_tool()],
                tool_choice={'type': 'tool', 'name': EXTRACTION_TOOL_NAME},
            )
        except Exception as exc:
            logger.error(f"Anthropic extraction call failed: {exc}")
            return RawModelOutput(error=f"anthropic_invoke_failed: {exc}")

        for block in response.content:
            if block.type == 'tool_use' and block.name == EXTRACTION_TOOL_NAME:
                return RawModelOutput(data=block.input,
                                      raw_text=json.dumps(block.input))
        return RawModelOutput(error='no_tool_use_block')

    def generate_email_draft(self, inbound_email, event_context, template_text=None,
                             refinement=None, previous_draft=None, user_prompt=None):
        """Generate email draft using Anthropic API (non-streaming)."""
        prompt = self._build_draft_prompt(
            inbound_email, event_context, template_text, refinement, previous_draft,
            user_prompt=user_prompt,
        )
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                temperature=0.4,
                messages=[{"role": "user", "content": prompt}]
            )
            return DraftGenerationResult(
                draft_text=message.content[0].text.strip(),
                tone='professional',
                confidence=0.85,
                warnings=[]
            )
        except Exception as e:
            logger.error(f"Anthropic draft generation failed: {e}")
            return DraftGenerationResult(
                draft_text='',
                confidence=0.0,
                warnings=[f'Draft generation failed: {str(e)}']
            )

    def generate_email_draft_stream(self, inbound_email, event_context, template_text=None,
                                     refinement=None, previous_draft=None, user_prompt=None):
        """Generate email draft with streaming using Anthropic API."""
        prompt = self._build_draft_prompt(
            inbound_email, event_context, template_text, refinement, previous_draft,
            user_prompt=user_prompt,
        )
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=1500,
                temperature=0.4,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Anthropic streaming draft generation failed: {e}")
            yield f'[Error: {str(e)}]'

    def health_check(self) -> bool:
        """
        Check if the Anthropic API is accessible.

        Returns:
            True if the API is reachable and responding
        """
        try:
            # Simple test message
            message = self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Say 'ok' and nothing else."}
                ]
            )
            return len(message.content) > 0
        except Exception as e:
            logger.error(f"Anthropic health check failed: {e}")
            return False

    def get_provider_name(self) -> str:
        """Return provider name with warning indicator."""
        return "AnthropicDevProvider [TEMPORARY - NOT FOR PRODUCTION]"


# ============================================================
#     END OF TEMPORARY DEVELOPMENT CODE
# ============================================================
