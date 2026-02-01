"""AI-powered document section detection using Claude's tool_use.

This service analyzes documents to identify logical sections with page ranges,
enabling users to select which sections to process for term replacement.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import anthropic
import structlog

from app.config import get_settings
from app.core.exceptions import AIServiceError

settings = get_settings()
logger = structlog.get_logger()

# Tool definition for structured section detection output
SECTION_DETECTION_TOOL = {
    "name": "identify_document_sections",
    "description": "Identify and report all logical sections in the document with their page ranges. "
                   "Call this tool after analyzing the document structure.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "description": "List of detected document sections",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Section heading or title as it appears in the document"
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of what this section contains"
                        },
                        "start_page": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Starting page number of this section"
                        },
                        "end_page": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Ending page number of this section (inclusive)"
                        },
                        "section_type": {
                            "type": "string",
                            "enum": [
                                "definitions",
                                "risk_disclosures",
                                "terms_and_conditions",
                                "investment_objectives",
                                "fund_management",
                                "fee_structure",
                                "regulatory",
                                "appendix",
                                "table_of_contents",
                                "cover_page",
                                "other"
                            ],
                            "description": "Category of the section for financial/legal documents"
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "Confidence score (0-1) in section boundary detection"
                        }
                    },
                    "required": ["title", "start_page", "end_page", "confidence"]
                }
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any concerns about ambiguous section boundaries or missing page information"
            }
        },
        "required": ["sections"]
    }
}


@dataclass
class DetectedSection:
    """A single detected document section."""
    id: str  # UUID for frontend selection tracking
    title: str
    description: str | None
    start_page: int
    end_page: int
    section_type: str | None
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "section_type": self.section_type,
            "confidence": self.confidence,
        }


@dataclass
class SectionDetectionResult:
    """Result of document section detection."""
    sections: list[DetectedSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "warnings": self.warnings,
            "page_count": self.page_count,
        }


class SectionDetector:
    """AI-powered section detector using Claude."""

    # Approximate tokens per character for chunking
    CHARS_PER_TOKEN = 4
    # Target chunk size in tokens (smaller than term replacement to stay focused)
    CHUNK_SIZE_TOKENS = 6000
    # Maximum retries for API calls
    MAX_RETRIES = 3
    # Base delay for exponential backoff (seconds)
    BASE_RETRY_DELAY = 1.0

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the detector.

        Args:
            api_key: Anthropic API key. If not provided, uses settings.
        """
        self.api_key = api_key or settings.anthropic_api_key
        if not self.api_key:
            raise AIServiceError("Anthropic API key required for section detection")

        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.model = "claude-sonnet-4-20250514"

    def _build_system_prompt(
        self,
        page_count: int | None,
        known_headers: list[str] | None = None,
    ) -> str:
        """Build the system prompt for section detection."""

        page_info = ""
        if page_count:
            page_info = f"\nThe document has {page_count} total pages."

        headers_info = ""
        if known_headers:
            headers_info = "\n\n## DETECTED HEADERS\nThe document parser found these headers:\n"
            for header in known_headers[:20]:  # Limit to 20 headers
                headers_info += f"  - {header}\n"
            headers_info += "\nUse these as hints, but verify against the actual content."

        system_prompt = f"""You are an expert document structure analyst specializing in legal and financial documents such as Private Placement Memorandums (PPMs), prospectuses, and fund offering documents.

## YOUR ROLE
Analyze the document to identify distinct logical sections that could be processed independently. Focus on major divisions that users would want to select for targeted processing.

## GUIDELINES
1. Identify major sections (chapters, articles, numbered sections)
2. Look for clear section headings and transitions
3. Map sections to page ranges based on content markers like "Page X" or sequential text flow
4. Be conservative with boundaries when they're unclear
5. Don't create too many small sections - focus on major divisions
6. Common sections in financial documents include:
   - Definitions / Glossary
   - Risk Factors / Risk Disclosures
   - Terms and Conditions
   - Investment Objectives
   - Management / Fund Management
   - Fee Structure / Expenses
   - Regulatory Information
   - Appendices
{page_info}
{headers_info}

## IMPORTANT
- If page numbers are embedded in the text (like "Page 5" or "-5-"), use those
- If no explicit page markers exist, estimate based on text position
- Section boundaries should not overlap
- Start page of one section should be after end page of previous section
- First section typically starts on page 1

## OUTPUT FORMAT
Use the identify_document_sections tool to report all detected sections with:
- Clear section titles as they appear in the document
- Brief descriptions of section content
- Start and end page numbers
- Confidence scores (0.9+ for clear sections, 0.7-0.9 for likely sections, below 0.7 for uncertain)
- Any warnings about ambiguous boundaries"""

        return system_prompt

    async def _call_api_with_retry(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
    ) -> anthropic.types.Message:
        """Call the Anthropic API with exponential backoff retry."""
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system,
                    messages=messages,
                    tools=tools,
                    tool_choice={"type": "tool", "name": "identify_document_sections"},
                )
                return response

            except anthropic.RateLimitError as e:
                last_error = e
                delay = self.BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Rate limited, retrying",
                    attempt=attempt + 1,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)

            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    last_error = e
                    delay = self.BASE_RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "Server error, retrying",
                        attempt=attempt + 1,
                        delay=delay,
                        status_code=e.status_code,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise AIServiceError(f"Anthropic API error: {e}") from e

            except anthropic.APIConnectionError as e:
                last_error = e
                delay = self.BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "Connection error, retrying",
                    attempt=attempt + 1,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)

        raise AIServiceError(f"API call failed after {self.MAX_RETRIES} retries: {last_error}")

    def _parse_tool_response(self, response: anthropic.types.Message) -> SectionDetectionResult:
        """Parse the tool use response into a SectionDetectionResult."""
        result = SectionDetectionResult()

        for block in response.content:
            if block.type == "tool_use" and block.name == "identify_document_sections":
                tool_input = block.input

                # Parse sections
                for section in tool_input.get("sections", []):
                    result.sections.append(DetectedSection(
                        id=str(uuid.uuid4()),  # Generate unique ID for selection
                        title=section.get("title", "Untitled Section"),
                        description=section.get("description"),
                        start_page=section.get("start_page", 1),
                        end_page=section.get("end_page", 1),
                        section_type=section.get("section_type"),
                        confidence=section.get("confidence", 0.5),
                    ))

                # Parse warnings
                result.warnings = tool_input.get("warnings", [])

                break

        return result

    async def detect_sections(
        self,
        document_text: str,
        page_count: int | None = None,
        known_headers: list[str] | None = None,
    ) -> SectionDetectionResult:
        """Detect sections in a document.

        Args:
            document_text: Full document text
            page_count: Known page count (optional)
            known_headers: Headers already extracted by parser (optional)

        Returns:
            SectionDetectionResult with detected sections
        """
        logger.info(
            "Starting section detection",
            text_length=len(document_text),
            page_count=page_count,
            num_known_headers=len(known_headers) if known_headers else 0,
        )

        # Build system prompt
        system_prompt = self._build_system_prompt(
            page_count=page_count,
            known_headers=known_headers,
        )

        # Truncate text if very long (we need structure, not full content)
        # Use representative samples from beginning, middle, and end
        max_chars = self.CHUNK_SIZE_TOKENS * self.CHARS_PER_TOKEN
        if len(document_text) > max_chars:
            # Take first 40%, middle 20%, last 40% of allowed size
            first_size = int(max_chars * 0.4)
            middle_size = int(max_chars * 0.2)
            last_size = int(max_chars * 0.4)

            first_part = document_text[:first_size]
            middle_start = len(document_text) // 2 - middle_size // 2
            middle_part = document_text[middle_start:middle_start + middle_size]
            last_part = document_text[-last_size:]

            document_text = (
                f"{first_part}\n\n[... CONTENT TRUNCATED FOR ANALYSIS ...]\n\n"
                f"{middle_part}\n\n[... CONTENT TRUNCATED FOR ANALYSIS ...]\n\n"
                f"{last_part}"
            )

        user_message = f"""Analyze the following document and identify all major sections with their page ranges.

## DOCUMENT TO ANALYZE
{document_text}

Please use the identify_document_sections tool to report all detected sections."""

        response = await self._call_api_with_retry(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            tools=[SECTION_DETECTION_TOOL],
        )

        result = self._parse_tool_response(response)
        result.page_count = page_count

        # Sort sections by start page
        result.sections.sort(key=lambda s: s.start_page)

        # Validate and fix any overlapping sections
        for i in range(1, len(result.sections)):
            prev = result.sections[i - 1]
            curr = result.sections[i]
            if curr.start_page <= prev.end_page:
                # Adjust previous section's end page
                prev.end_page = curr.start_page - 1
                result.warnings.append(
                    f"Adjusted overlapping sections: '{prev.title}' and '{curr.title}'"
                )

        # Validate page ranges against known page count
        if page_count:
            for section in result.sections:
                if section.end_page > page_count:
                    section.end_page = page_count
                    result.warnings.append(
                        f"Adjusted section '{section.title}' end page to match document length"
                    )

        logger.info(
            "Section detection complete",
            num_sections=len(result.sections),
            num_warnings=len(result.warnings),
        )

        return result


# Singleton instance
_section_detector_instance: SectionDetector | None = None


def get_section_detector() -> SectionDetector:
    """Get section detector singleton instance.

    Raises:
        AIServiceError: If Anthropic API key is not configured
    """
    global _section_detector_instance
    if _section_detector_instance is None:
        _section_detector_instance = SectionDetector()
    return _section_detector_instance
