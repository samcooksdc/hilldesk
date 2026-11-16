# SPDX-License-Identifier: Apache-2.0
"""
Amazon Bedrock LLM Provider - PRODUCTION USE.

This is the ONLY LLM provider approved for production deployment.
It uses the boto3 Bedrock Runtime client to access Claude models via
AWS VPC Endpoints, ensuring no public internet egress.

Production requirements satisfied:
- All LLM calls route through AWS Bedrock (no third-party SaaS APIs)
- Traffic flows through VPC Endpoints (no public internet)
- Supports GovCloud regions (us-gov-west-1)
- Compatible with House Direct Connect architecture

Usage:
    Set LLM_PROVIDER=bedrock in your environment or Django settings.

Configuration:
    AWS_REGION: AWS region (default: us-gov-west-1)
    BEDROCK_EXTRACTION_MODEL: Model for the single extraction call + drafts
    BEDROCK_KB_ID: Optional Knowledge Base ID for RAG
"""

import json
import logging
from typing import Optional

from django.conf import settings

from .base import BaseLLMProvider, DraftGenerationResult
from .schema import (
    EXTRACTION_SYSTEM_PROMPT, EXTRACTION_TOOL_NAME, MessageBundle,
    RawModelOutput, build_extraction_tool, build_extraction_user_content,
)

logger = logging.getLogger(__name__)


class BedrockProvider(BaseLLMProvider):
    """
    Production LLM provider using Amazon Bedrock.

    This is the approved provider for production use. It accesses
    Claude models via the AWS Bedrock Runtime API through VPC Endpoints.
    """

    # Default model ID for Bedrock (env-overridden in every real deployment;
    # the funnel replaced the separate classification model entirely)
    DEFAULT_EXTRACTION_MODEL = 'anthropic.claude-3-sonnet-20240229-v1:0'
    DEFAULT_REGION = 'us-gov-west-1'

    def __init__(self):
        """
        Initialize the Bedrock provider.

        The boto3 clients are lazily initialized to avoid import errors
        in development environments without AWS credentials.
        """
        # Configuration from Django settings
        self.region = getattr(settings, 'AWS_REGION', self.DEFAULT_REGION)
        self.extraction_model = getattr(
            settings,
            'BEDROCK_EXTRACTION_MODEL',
            self.DEFAULT_EXTRACTION_MODEL
        )
        self.kb_id = getattr(settings, 'BEDROCK_KB_ID', None)

        # Lazy-initialized boto3 clients
        self._runtime_client = None
        self._agent_client = None

        logger.info(
            f"BedrockProvider initialized: region={self.region}, "
            f"extraction_model={self.extraction_model}"
        )

    @property
    def runtime_client(self):
        """
        Lazily initialize the Bedrock Runtime client.

        Returns:
            boto3 bedrock-runtime client
        """
        if self._runtime_client is None:
            import boto3
            self._runtime_client = boto3.client(
                'bedrock-runtime',
                region_name=self.region
            )
            logger.debug(f"Bedrock Runtime client initialized for region {self.region}")
        return self._runtime_client

    @property
    def agent_client(self):
        """
        Lazily initialize the Bedrock Agent Runtime client.

        Used for Knowledge Base RAG queries.

        Returns:
            boto3 bedrock-agent-runtime client
        """
        if self._agent_client is None:
            import boto3
            self._agent_client = boto3.client(
                'bedrock-agent-runtime',
                region_name=self.region
            )
            logger.debug(f"Bedrock Agent Runtime client initialized for region {self.region}")
        return self._agent_client

    def _invoke_model(
        self,
        prompt: str,
        model_id: str,
        max_tokens: int = 1000,
        temperature: float = 0.1
    ) -> str:
        """
        Invoke a Bedrock model with the given prompt.

        Args:
            prompt: The user prompt to send
            model_id: The Bedrock model ID to use
            max_tokens: Maximum tokens in the response
            temperature: Sampling temperature (0.0-1.0)

        Returns:
            The model's text response

        Raises:
            Exception: If the API call fails
        """
        # Build request body for Claude models on Bedrock
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        })

        logger.debug(f"Invoking Bedrock model: {model_id}")

        response = self.runtime_client.invoke_model(
            modelId=model_id,
            body=body,
            contentType='application/json',
            accept='application/json'
        )

        # Parse response
        response_body = json.loads(response['body'].read())

        # Extract text from Claude response format
        if 'content' in response_body and len(response_body['content']) > 0:
            return response_body['content'][0]['text']
        else:
            raise ValueError("Unexpected response format from Bedrock")

    def extract_candidates(self, bundle: MessageBundle) -> RawModelOutput:
        """
        The single extraction call (spec §7): one invoke_model with a FORCED
        tool-use definition built from the candidate-set schema, so the model
        can only answer through the schema. Images / scan-only PDFs ride along
        as content blocks — OCR stays inside this one call.
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

        # NOTE: no `thinking` field — the legacy claude-3 body rejects it, and
        # newer Claude models on Bedrock require thinking DISABLED alongside a
        # forced tool_choice anyway (omit or disable when upgrading the model).
        body = json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 4000,
            'system': EXTRACTION_SYSTEM_PROMPT,
            'messages': [{'role': 'user', 'content': content}],
            'tools': [build_extraction_tool()],
            'tool_choice': {'type': 'tool', 'name': EXTRACTION_TOOL_NAME},
        })

        try:
            response = self.runtime_client.invoke_model(
                modelId=self.extraction_model,
                body=body,
                contentType='application/json',
                accept='application/json',
            )
            response_body = json.loads(response['body'].read())
        except Exception as exc:
            logger.error(f"Bedrock extraction call failed: {exc}")
            return RawModelOutput(error=f"bedrock_invoke_failed: {exc}")

        for block in response_body.get('content', []):
            if block.get('type') == 'tool_use' and block.get('name') == EXTRACTION_TOOL_NAME:
                return RawModelOutput(data=block.get('input'),
                                      raw_text=json.dumps(block.get('input')))
        return RawModelOutput(
            error='no_tool_use_block',
            raw_text=json.dumps(response_body.get('content', []))[:2000],
        )

    def generate_email_draft(self, inbound_email, event_context, template_text=None,
                             refinement=None, previous_draft=None, user_prompt=None):
        """
        Generate email draft using Bedrock (non-streaming).
        """
        prompt = self._build_draft_prompt(
            inbound_email, event_context, template_text, refinement, previous_draft,
            user_prompt=user_prompt,
        )
        try:
            response_text = self._invoke_model(
                prompt=prompt,
                model_id=self.extraction_model,
                max_tokens=1500,
                temperature=0.4
            )
            return DraftGenerationResult(
                draft_text=response_text.strip(),
                tone='professional',
                confidence=0.85,
                warnings=[]
            )
        except Exception as e:
            logger.error(f"Bedrock draft generation failed: {e}")
            return DraftGenerationResult(
                draft_text='',
                tone='professional',
                confidence=0.0,
                warnings=[f'Draft generation failed: {str(e)}']
            )

    def generate_email_draft_stream(self, inbound_email, event_context, template_text=None,
                                     refinement=None, previous_draft=None, user_prompt=None):
        """
        Generate email draft using Bedrock with streaming.
        Uses invoke_model_with_response_stream and yields text chunks.
        """
        prompt = self._build_draft_prompt(
            inbound_email, event_context, template_text, refinement, previous_draft,
            user_prompt=user_prompt,
        )
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "temperature": 0.4,
            "messages": [{"role": "user", "content": prompt}]
        })

        try:
            response = self.runtime_client.invoke_model_with_response_stream(
                modelId=self.extraction_model,
                body=body,
                contentType='application/json',
                accept='application/json'
            )
            for event in response.get('body', []):
                chunk = json.loads(event['chunk']['bytes'])
                if chunk.get('type') == 'content_block_delta':
                    delta = chunk.get('delta', {})
                    if delta.get('type') == 'text_delta':
                        yield delta.get('text', '')
        except Exception as e:
            logger.error(f"Bedrock streaming draft generation failed: {e}")
            yield f'[Error: {str(e)}]'

    def retrieve_and_generate(self, query: str, kb_id: Optional[str] = None) -> str:
        """
        Query a Bedrock Knowledge Base with RAG (Retrieve and Generate).

        This method uses the Bedrock Agent Runtime to query a Knowledge Base
        and generate a response using the retrieved context.

        Args:
            query: The user's question or query
            kb_id: Optional Knowledge Base ID (uses settings if not provided)

        Returns:
            The generated response text

        Raises:
            ValueError: If no Knowledge Base ID is configured
        """
        kb_id = kb_id or self.kb_id
        if not kb_id:
            raise ValueError(
                "No Bedrock Knowledge Base ID configured. "
                "Set BEDROCK_KB_ID in Django settings."
            )

        logger.debug(f"Querying Knowledge Base: {kb_id}")

        response = self.agent_client.retrieve_and_generate(
            input={'text': query},
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': kb_id,
                    'modelArn': f'arn:aws:bedrock:{self.region}::foundation-model/{self.extraction_model}'
                }
            }
        )

        return response['output']['text']

    def retrieve(self, query: str, kb_id: Optional[str] = None, max_results: int = 5) -> list:
        """
        Retrieve relevant documents from a Bedrock Knowledge Base.

        This method retrieves documents without generating a response,
        useful for showing source documents to users.

        Args:
            query: The search query
            kb_id: Optional Knowledge Base ID (uses settings if not provided)
            max_results: Maximum number of results to return

        Returns:
            List of retrieved document chunks with metadata
        """
        kb_id = kb_id or self.kb_id
        if not kb_id:
            raise ValueError(
                "No Bedrock Knowledge Base ID configured. "
                "Set BEDROCK_KB_ID in Django settings."
            )

        logger.debug(f"Retrieving from Knowledge Base: {kb_id}")

        response = self.agent_client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={'text': query},
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': max_results
                }
            }
        )

        return response.get('retrievalResults', [])

    def health_check(self) -> bool:
        """
        Check if Bedrock is accessible and responding.

        Performs a minimal model invocation to verify connectivity.

        Returns:
            True if Bedrock is healthy and responding
        """
        try:
            # Simple test invocation
            response = self._invoke_model(
                prompt="Say 'ok' and nothing else.",
                model_id=self.extraction_model,
                max_tokens=10,
                temperature=0.0
            )
            logger.info("Bedrock health check passed")
            return len(response) > 0
        except Exception as e:
            logger.error(f"Bedrock health check failed: {e}")
            return False

    def get_provider_name(self) -> str:
        """Return provider name with region info."""
        return f"BedrockProvider ({self.region})"
