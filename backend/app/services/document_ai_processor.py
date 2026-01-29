"""AI-powered document processing service using Claude's tool_use.

This service analyzes documents to identify term replacements based on
reference examples, using Claude's tool_use feature for reliable structured outputs.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic
import structlog

from app.config import get_settings
from app.core.exceptions import AIServiceError
from app.models.database import ReferenceExample
from app.services.document_parser import DocumentContent

settings = get_settings()
logger = structlog.get_logger()

# Tool definition for structured term replacement output
TERM_REPLACEMENT_TOOL = {
    "name": "record_term_replacements",
    "description": "Record all term replacements that should be made in the document. "
                   "Call this tool with all identified replacements after analyzing the document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "replacements": {
                "type": "array",
                "description": "List of term replacements to make",
                "items": {
                    "type": "object",
                    "properties": {
                        "original_term": {
                            "type": "string",
                            "description": "The exact term or phrase to replace (as it appears in the document)"
                        },
                        "replacement_term": {
                            "type": "string",
                            "description": "The new term or phrase to use"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation of why this replacement is appropriate"
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "Confidence score (0-1) in this replacement"
                        },
                        "category": {
                            "type": "string",
                            "enum": ["legal", "financial", "technical", "formatting", "terminology", "other"],
                            "description": "Category of the replacement"
                        }
                    },
                    "required": ["original_term", "replacement_term", "reasoning", "confidence"]
                }
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any ambiguous cases, concerns, or terms that require human review"
            },
            "summary": {
                "type": "string",
                "description": "Brief summary of the analysis and main patterns found"
            }
        },
        "required": ["replacements"]
    }
}


@dataclass
class TermReplacement:
    """A single term replacement."""
    original_term: str
    replacement_term: str
    reasoning: str
    confidence: float
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_term": self.original_term,
            "replacement_term": self.replacement_term,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "category": self.category,
        }


@dataclass
class TermReplacementResult:
    """Result of document analysis for term replacements."""
    replacements: list[TermReplacement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: str | None = None
    chunks_processed: int = 0
    total_chunks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "replacements": [r.to_dict() for r in self.replacements],
            "warnings": self.warnings,
            "summary": self.summary,
            "chunks_processed": self.chunks_processed,
            "total_chunks": self.total_chunks,
        }

    def merge(self, other: "TermReplacementResult") -> None:
        """Merge another result into this one, deduplicating replacements."""
        existing_pairs = {(r.original_term.lower(), r.replacement_term.lower())
                         for r in self.replacements}

        for replacement in other.replacements:
            key = (replacement.original_term.lower(), replacement.replacement_term.lower())
            if key not in existing_pairs:
                self.replacements.append(replacement)
                existing_pairs.add(key)

        self.warnings.extend(other.warnings)
        self.chunks_processed += other.chunks_processed


class DocumentAIProcessor:
    """AI processor for document term replacement analysis using Claude."""

    # Approximate tokens per character for chunking
    CHARS_PER_TOKEN = 4
    # Target chunk size in tokens
    CHUNK_SIZE_TOKENS = 4000
    # Overlap between chunks in tokens
    CHUNK_OVERLAP_TOKENS = 200
    # Maximum retries for API calls
    MAX_RETRIES = 3
    # Base delay for exponential backoff (seconds)
    BASE_RETRY_DELAY = 1.0

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the processor.

        Args:
            api_key: Anthropic API key. If not provided, uses settings.
        """
        self.api_key = api_key or settings.anthropic_api_key
        if not self.api_key:
            raise AIServiceError("Anthropic API key required for document processing")

        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.model = "claude-sonnet-4-20250514"

    def _build_system_prompt(
        self,
        reference_examples: list[ReferenceExample],
        protected_terms: list[str],
    ) -> str:
        """Build the system prompt with context about the task."""

        # Build reference examples section
        examples_text = ""
        if reference_examples:
            examples_text = "\n\n## REFERENCE EXAMPLES\n"
            examples_text += "Learn from these before/after transformation examples:\n\n"

            for i, example in enumerate(reference_examples, 1):
                examples_text += f"### Example {i}: {example.name}\n"

                # Include term mappings if available
                if example.term_mappings and example.term_mappings.get("mappings"):
                    examples_text += "Key transformations:\n"
                    for mapping in example.term_mappings["mappings"][:10]:  # Limit to 10 mappings
                        orig = mapping.get("original_term", "")
                        conv = mapping.get("converted_term", "")
                        if orig and conv:
                            examples_text += f'  - "{orig}" → "{conv}"\n'

                # Include truncated original/converted text for context
                orig_preview = example.original_text[:500] + "..." if len(example.original_text) > 500 else example.original_text
                conv_preview = example.converted_text[:500] + "..." if len(example.converted_text) > 500 else example.converted_text

                examples_text += f"\nOriginal excerpt:\n{orig_preview}\n"
                examples_text += f"\nConverted excerpt:\n{conv_preview}\n"
                examples_text += "\n---\n"

        # Build protected terms section
        protected_text = ""
        if protected_terms:
            protected_text = "\n\n## PROTECTED TERMS (DO NOT MODIFY)\n"
            protected_text += "The following terms are template-defined and must NOT be changed:\n"
            for term in protected_terms:
                protected_text += f"  - {term}\n"

        system_prompt = f"""You are an expert document analyst specializing in legal and financial document transformation. Your task is to analyze a document and identify terms that should be replaced based on established patterns and reference examples.

## YOUR ROLE
You are helping to transform documents to match a specific style, terminology, and format based on reference examples. You should identify terms in the input document that should be changed to match the patterns seen in the reference examples.

## GUIDELINES
1. Focus on substantive terminology changes, not minor formatting
2. Look for consistent patterns in the reference examples
3. Be conservative - only suggest changes you're confident about
4. Preserve the document's meaning while updating terminology
5. Pay attention to context - the same word might need different replacements in different contexts
6. NEVER suggest changes to protected terms
7. Assign confidence scores based on how clear the pattern is from the examples
{examples_text}
{protected_text}

## OUTPUT FORMAT
Use the record_term_replacements tool to report your findings. Include:
- All term replacements with exact original text
- Reasoning for each replacement
- Confidence scores (0.9+ for clear patterns, 0.7-0.9 for likely patterns, below 0.7 for uncertain)
- Any warnings about ambiguous cases
- A brief summary of the main transformation patterns you applied"""

        return system_prompt

    def _chunk_document(self, text: str) -> list[str]:
        """Split document into overlapping chunks for processing.

        Args:
            text: Full document text

        Returns:
            List of text chunks
        """
        chunk_size_chars = self.CHUNK_SIZE_TOKENS * self.CHARS_PER_TOKEN
        overlap_chars = self.CHUNK_OVERLAP_TOKENS * self.CHARS_PER_TOKEN

        if len(text) <= chunk_size_chars:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size_chars

            # Try to break at paragraph or sentence boundary
            if end < len(text):
                # Look for paragraph break
                para_break = text.rfind("\n\n", start + chunk_size_chars // 2, end)
                if para_break > start:
                    end = para_break + 2
                else:
                    # Look for sentence break
                    for sep in [". ", "! ", "? ", "\n"]:
                        sent_break = text.rfind(sep, start + chunk_size_chars // 2, end)
                        if sent_break > start:
                            end = sent_break + len(sep)
                            break

            chunks.append(text[start:end].strip())
            start = end - overlap_chars

            # Avoid infinite loop
            if start >= len(text) - overlap_chars:
                break

        return chunks

    async def _call_api_with_retry(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
    ) -> anthropic.types.Message:
        """Call the Anthropic API with exponential backoff retry.

        Args:
            messages: Chat messages
            system: System prompt
            tools: Tool definitions

        Returns:
            API response message
        """
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system,
                    messages=messages,
                    tools=tools,
                    tool_choice={"type": "tool", "name": "record_term_replacements"},
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
                    # Server error, retry
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
                    # Client error, don't retry
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

    def _parse_tool_response(self, response: anthropic.types.Message) -> TermReplacementResult:
        """Parse the tool use response into a TermReplacementResult.

        Args:
            response: API response message

        Returns:
            Parsed result
        """
        result = TermReplacementResult(chunks_processed=1, total_chunks=1)

        for block in response.content:
            if block.type == "tool_use" and block.name == "record_term_replacements":
                tool_input = block.input

                # Parse replacements
                for rep in tool_input.get("replacements", []):
                    result.replacements.append(TermReplacement(
                        original_term=rep.get("original_term", ""),
                        replacement_term=rep.get("replacement_term", ""),
                        reasoning=rep.get("reasoning", ""),
                        confidence=rep.get("confidence", 0.5),
                        category=rep.get("category"),
                    ))

                # Parse warnings
                result.warnings = tool_input.get("warnings", [])

                # Parse summary
                result.summary = tool_input.get("summary")

                break

        return result

    async def _process_chunk(
        self,
        chunk: str,
        chunk_index: int,
        total_chunks: int,
        system_prompt: str,
    ) -> TermReplacementResult:
        """Process a single document chunk.

        Args:
            chunk: Text chunk to process
            chunk_index: Index of this chunk (0-based)
            total_chunks: Total number of chunks
            system_prompt: System prompt with context

        Returns:
            Analysis result for this chunk
        """
        chunk_context = ""
        if total_chunks > 1:
            chunk_context = f"\n\n[This is chunk {chunk_index + 1} of {total_chunks}. " \
                           f"Focus on terms in this section, noting any that may continue from previous chunks.]"

        user_message = f"""Analyze the following document section and identify all terms that should be replaced based on the reference examples and patterns provided.

## DOCUMENT TO ANALYZE
{chunk}
{chunk_context}

Please use the record_term_replacements tool to report all identified replacements."""

        response = await self._call_api_with_retry(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            tools=[TERM_REPLACEMENT_TOOL],
        )

        result = self._parse_tool_response(response)
        result.chunks_processed = 1
        result.total_chunks = total_chunks

        return result

    async def analyze_document_for_replacements(
        self,
        document_content: DocumentContent,
        reference_examples: list[ReferenceExample],
        protected_terms: list[str] | None = None,
    ) -> TermReplacementResult:
        """Analyze a document to identify term replacements.

        This is the main entry point for document analysis. It:
        1. Builds context from reference examples
        2. Chunks the document if needed
        3. Processes each chunk with Claude
        4. Merges and deduplicates results

        Args:
            document_content: Parsed document content
            reference_examples: Reference examples for learning patterns
            protected_terms: Terms that should never be changed

        Returns:
            TermReplacementResult with all identified replacements
        """
        logger.info(
            "Starting document analysis",
            document_title=document_content.title,
            word_count=document_content.word_count,
            num_examples=len(reference_examples),
            num_protected_terms=len(protected_terms or []),
        )

        # Build system prompt with context
        system_prompt = self._build_system_prompt(
            reference_examples=reference_examples,
            protected_terms=protected_terms or [],
        )

        # Chunk the document if needed
        chunks = self._chunk_document(document_content.full_text)
        total_chunks = len(chunks)

        logger.info(f"Document split into {total_chunks} chunks")

        # Process chunks
        if total_chunks == 1:
            # Single chunk, process directly
            result = await self._process_chunk(
                chunk=chunks[0],
                chunk_index=0,
                total_chunks=1,
                system_prompt=system_prompt,
            )
        else:
            # Multiple chunks, process and merge
            result = TermReplacementResult(total_chunks=total_chunks)

            for i, chunk in enumerate(chunks):
                logger.info(f"Processing chunk {i + 1}/{total_chunks}")

                chunk_result = await self._process_chunk(
                    chunk=chunk,
                    chunk_index=i,
                    total_chunks=total_chunks,
                    system_prompt=system_prompt,
                )

                result.merge(chunk_result)

            # Generate overall summary if multiple chunks
            if result.replacements:
                result.summary = (
                    f"Analyzed {total_chunks} document sections. "
                    f"Found {len(result.replacements)} unique term replacements. "
                    f"{len(result.warnings)} items flagged for review."
                )

        # Sort replacements by confidence (highest first)
        result.replacements.sort(key=lambda r: r.confidence, reverse=True)

        # Deduplicate warnings
        result.warnings = list(dict.fromkeys(result.warnings))

        logger.info(
            "Document analysis complete",
            total_replacements=len(result.replacements),
            total_warnings=len(result.warnings),
            chunks_processed=result.chunks_processed,
        )

        return result

    async def apply_replacements(
        self,
        text: str,
        replacements: list[TermReplacement],
        min_confidence: float = 0.7,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Apply term replacements to text.

        Args:
            text: Original text
            replacements: List of replacements to apply
            min_confidence: Minimum confidence threshold

        Returns:
            Tuple of (modified text, list of applied changes)
        """
        # Filter by confidence
        applicable = [r for r in replacements if r.confidence >= min_confidence]

        # Sort by original term length (longest first) to avoid partial replacements
        applicable.sort(key=lambda r: len(r.original_term), reverse=True)

        modified_text = text
        applied_changes = []

        for replacement in applicable:
            # Use word boundary matching for safety
            pattern = re.compile(
                r'\b' + re.escape(replacement.original_term) + r'\b',
                re.IGNORECASE
            )

            matches = list(pattern.finditer(modified_text))
            if matches:
                # Apply replacement
                modified_text = pattern.sub(replacement.replacement_term, modified_text)
                applied_changes.append({
                    "original": replacement.original_term,
                    "replacement": replacement.replacement_term,
                    "occurrences": len(matches),
                    "confidence": replacement.confidence,
                    "reasoning": replacement.reasoning,
                })

        return modified_text, applied_changes


# Singleton instance
_document_ai_processor_instance: DocumentAIProcessor | None = None


def get_document_ai_processor() -> DocumentAIProcessor:
    """Get document AI processor singleton instance.

    Raises:
        AIServiceError: If Anthropic API key is not configured
    """
    global _document_ai_processor_instance
    if _document_ai_processor_instance is None:
        _document_ai_processor_instance = DocumentAIProcessor()
    return _document_ai_processor_instance
