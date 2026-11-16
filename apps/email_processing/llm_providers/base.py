# SPDX-License-Identifier: Apache-2.0
"""
Base LLM Provider Interface.

One structured extraction call per message (spec §7) — the old
classify→extract pair is gone; the deterministic funnel replaced
classification. Providers also generate email drafts (unchanged surface used
by draft_generation_service).

The provider has no tools and no write path: it returns data into a candidate
row that only a human can act on.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import logging

from .schema import MessageBundle, RawModelOutput

logger = logging.getLogger(__name__)


@dataclass
class DraftGenerationResult:
    """Result of AI email draft generation."""
    draft_text: str
    tone: str = 'professional'
    confidence: float = 0.8
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'draft_text': self.draft_text,
            'tone': self.tone,
            'confidence': self.confidence,
            'warnings': self.warnings
        }


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    All LLM provider implementations (Bedrock, Mock, AnthropicDev) must
    inherit from this class and implement the abstract methods.
    """

    @abstractmethod
    def extract_candidates(self, bundle: MessageBundle) -> RawModelOutput:
        """
        The single extraction call: one message bundle in, one candidate set out.

        Implementations invoke the model exactly once with a forced
        structured-output (tool-use) definition built from
        ``schema.CANDIDATE_SET_SCHEMA``. The caller — not the provider — is
        responsible for schema validation, the one repair retry
        (``bundle.repair_error``), and escalation on persistent failure.

        Returns:
            RawModelOutput with ``data`` (parsed dict) on success, or
            ``error`` set on invocation/parse failure. Never raises for
            model-shaped problems; raises only for infrastructure failures the
            task layer should retry.
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        Check if the provider is operational.

        Returns:
            True if the provider is healthy and ready to process requests
        """
        pass

    def generate_email_draft(
        self,
        inbound_email: str,
        event_context: Dict[str, Any],
        template_text: Optional[str] = None,
        refinement: Optional[str] = None,
        previous_draft: Optional[str] = None,
    ) -> DraftGenerationResult:
        """
        Generate a professional email draft response.

        Args:
            inbound_email: The original inbound email text
            event_context: Dictionary with event metadata (title, date, etc.)
            template_text: Optional template text to base the draft on
            refinement: Optional refinement instruction (shorter/more_formal/more_friendly/try_again)
            previous_draft: Optional previous draft for iterative refinement

        Returns:
            DraftGenerationResult with draft text and metadata
        """
        raise NotImplementedError("Subclass must implement generate_email_draft()")

    def generate_email_draft_stream(
        self,
        inbound_email: str,
        event_context: Dict[str, Any],
        template_text: Optional[str] = None,
        refinement: Optional[str] = None,
        previous_draft: Optional[str] = None,
    ):
        """
        Generate email draft with streaming. Yields text chunks.
        Default implementation falls back to non-streaming.
        """
        result = self.generate_email_draft(
            inbound_email, event_context, template_text, refinement, previous_draft
        )
        yield result.draft_text

    def get_provider_name(self) -> str:
        """
        Return the provider identifier.

        Returns:
            String name of this provider class
        """
        return self.__class__.__name__

    def _build_draft_prompt(
        self,
        inbound_email: str,
        event_context: Dict[str, Any],
        template_text: Optional[str] = None,
        refinement: Optional[str] = None,
        previous_draft: Optional[str] = None,
        user_prompt: Optional[str] = None,
    ) -> str:
        """
        Build the prompt for email draft generation with congressional guardrails.

        Args:
            inbound_email: The original email text
            event_context: Event metadata dictionary
            template_text: Optional template to base draft on
            refinement: Optional refinement instruction
            previous_draft: Optional previous draft for iteration

        Returns:
            Formatted prompt string
        """
        # Build event context summary
        ctx_parts = []
        if event_context.get('event_title'):
            ctx_parts.append(f"Event: {event_context['event_title']}")
        if event_context.get('event_date'):
            ctx_parts.append(f"Date: {event_context['event_date']}")
        if event_context.get('event_time'):
            ctx_parts.append(f"Time: {event_context['event_time']}")
        if event_context.get('event_location'):
            ctx_parts.append(f"Location: {event_context['event_location']}")
        if event_context.get('organization'):
            ctx_parts.append(f"Organization: {event_context['organization']}")
        if event_context.get('member_name'):
            ctx_parts.append(f"Member: {event_context['member_name']}")
        if event_context.get('staffer_name'):
            ctx_parts.append(f"Staffer: {event_context['staffer_name']}")

        event_summary = "\n".join(ctx_parts) if ctx_parts else "No event details available."

        # Refinement instructions
        refinement_text = ""
        if refinement == 'shorter':
            refinement_text = "\nIMPORTANT: Make this draft SHORTER and more concise. Aim for 2-3 sentences."
        elif refinement == 'more_formal':
            refinement_text = "\nIMPORTANT: Make this draft MORE FORMAL. Use formal congressional language."
        elif refinement == 'more_friendly':
            refinement_text = "\nIMPORTANT: Make this draft MORE FRIENDLY and warm while maintaining professionalism."
        elif refinement == 'try_again':
            refinement_text = "\nIMPORTANT: Generate a completely different draft with a fresh approach."

        # Previous draft section
        prev_draft_text = ""
        if previous_draft:
            prev_draft_text = f"\n\nPREVIOUS DRAFT (for reference - generate an improved version):\n{previous_draft}"

        # Template section
        template_section = ""
        if template_text:
            template_section = f"\n\nTEMPLATE TO BASE DRAFT ON:\n{template_text}\nUse this template as a starting point but personalize it with the event details."

        # Staff instructions override built-in guidelines when provided
        if user_prompt:
            return f"""You are a professional email assistant for a U.S. Congressional office. Draft a response to the following inbound email.

STAFF INSTRUCTIONS (follow these as your primary directive):
{user_prompt}

INBOUND EMAIL:
{inbound_email}

EVENT DETAILS:
{event_summary}
{template_section}
{prev_draft_text}
{refinement_text}

Generate ONLY the email body text. Do not include subject line, greeting prefix like "Subject:", or signature."""

        return f"""You are a professional email assistant for a U.S. Congressional office. Draft a response to the following inbound email.

CRITICAL GUARDRAILS:
- Professional, warm tone appropriate for congressional correspondence
- Scheduling and logistics language ONLY
- Do NOT take any policy positions - if the email raises policy issues, defer with "the office will follow up on this matter"
- Do NOT fabricate information - leave {{placeholder}} markers for any information you don't have
- Do NOT include a signature block - staff signature is auto-inserted separately
- Match response length to type: 3-5 sentences for RSVP/acknowledgment, longer for follow-ups with action items
- Use the event details provided to personalize the response

INBOUND EMAIL:
{inbound_email}

EVENT DETAILS:
{event_summary}
{template_section}
{prev_draft_text}
{refinement_text}

Generate ONLY the email body text. Do not include subject line, greeting prefix like "Subject:", or signature."""

    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse JSON from LLM response, handling common formatting issues.

        Args:
            response_text: Raw text response from the LLM

        Returns:
            Parsed JSON as a dictionary

        Raises:
            ValueError: If JSON cannot be parsed
        """
        import json
        import re

        # Clean up the response
        text = response_text.strip()

        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            text = json_match.group(1).strip()

        # Remove any leading/trailing non-JSON content
        # Find the first { and last }
        start_idx = text.find('{')
        end_idx = text.rfind('}')

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            text = text[start_idx:end_idx + 1]

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {response_text}")
            raise ValueError(f"Invalid JSON in LLM response: {e}")
