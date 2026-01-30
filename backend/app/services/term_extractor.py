"""Service for extracting defined terms from documents using AI."""

import json
import re
from dataclasses import dataclass

from app.services.ai_service import get_ai_service
from app.core.exceptions import AIServiceError


@dataclass
class ExtractedTerm:
    """Represents an extracted defined term."""
    term: str
    contexts: list[str]  # Sentences/paragraphs where the term appears
    definition: str | None = None  # If a formal definition is found
    suggested_replacement: str | None = None  # AI suggestion based on learned patterns


async def extract_defined_terms(
    document_text: str,
    existing_mappings: list[dict[str, str]] | None = None,
) -> list[ExtractedTerm]:
    """
    Extract defined terms from a document using AI.

    Args:
        document_text: The full text of the document
        existing_mappings: Optional list of existing term mappings to suggest replacements

    Returns:
        List of ExtractedTerm objects with terms and their contexts
    """
    ai_service = get_ai_service()

    # Build the prompt for term extraction
    system_prompt = """You are a legal document analyst specializing in investment fund documents and risk disclosures.

Your task is to identify DEFINED TERMS from the document. Defined terms are typically:
- Capitalized words or phrases (e.g., "Investment Manager", "the Fund", "Limited Partners")
- Terms in quotation marks that are being defined
- Terms in parentheses that serve as shorthand definitions
- Terms followed by "means", "refers to", or similar defining language

For each term found, extract:
1. The exact term as it appears (preserving capitalization)
2. 2-3 example sentences showing how the term is used in context
3. Any formal definition if one exists in the document

Return your response as a JSON array with this structure:
[
  {
    "term": "Investment Manager",
    "contexts": [
      "The Investment Manager shall have full discretion...",
      "Fees payable to the Investment Manager include..."
    ],
    "definition": "ABC Capital LLC, the investment manager appointed under this Agreement"
  }
]

Focus on finding 10-30 key defined terms. Prioritize terms that:
- Appear multiple times in the document
- Are specific to this document (not generic legal terms like "herein" or "thereof")
- Would likely need to be mapped/replaced when adapting the document"""

    # Truncate document if too long (keep first ~15k chars for context)
    truncated_text = document_text[:15000]
    if len(document_text) > 15000:
        truncated_text += "\n\n[Document truncated for analysis...]"

    prompt = f"""Analyze this document and extract all defined terms:

---
{truncated_text}
---

Return ONLY a valid JSON array of extracted terms."""

    try:
        response = await ai_service.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=4000,
            temperature=0.1,
        )

        # Parse JSON response
        # Find JSON array in response
        start = response.find("[")
        end = response.rfind("]") + 1

        if start >= 0 and end > start:
            terms_data = json.loads(response[start:end])
        else:
            raise ValueError("No JSON array found in response")

        # Convert to ExtractedTerm objects
        extracted_terms = []
        for item in terms_data:
            term = ExtractedTerm(
                term=item.get("term", ""),
                contexts=item.get("contexts", []),
                definition=item.get("definition"),
                suggested_replacement=None,
            )

            # If we have existing mappings, suggest replacements
            if existing_mappings and term.term:
                for mapping in existing_mappings:
                    if mapping.get("original_text", "").lower() == term.term.lower():
                        term.suggested_replacement = mapping.get("converted_text")
                        break

            if term.term:  # Only add if term is not empty
                extracted_terms.append(term)

        return extracted_terms

    except json.JSONDecodeError as e:
        raise AIServiceError(f"Failed to parse AI response as JSON: {e}") from e
    except Exception as e:
        raise AIServiceError(f"Term extraction failed: {e}") from e


async def suggest_term_mappings(
    terms: list[str],
    existing_mappings: list[dict[str, str]],
    document_context: str | None = None,
) -> dict[str, str | None]:
    """
    Use AI to suggest mappings for terms based on existing patterns.

    Args:
        terms: List of terms to suggest mappings for
        existing_mappings: Existing term mappings to learn from
        document_context: Optional context from the document

    Returns:
        Dictionary mapping terms to suggested replacements (None if no suggestion)
    """
    if not existing_mappings:
        return {term: None for term in terms}

    ai_service = get_ai_service()

    # Build examples from existing mappings
    examples = "\n".join([
        f"- \"{m['original_text']}\" → \"{m['corrected_text']}\""
        for m in existing_mappings[:20]  # Limit to 20 examples
    ])

    terms_list = "\n".join([f"- {term}" for term in terms])

    system_prompt = """You are helping standardize terminology in legal/investment documents.
Based on the existing mapping patterns provided, suggest appropriate replacements for new terms.
If a term doesn't fit any pattern or should remain unchanged, output null for that term.

Return a JSON object mapping each term to its suggested replacement (or null)."""

    prompt = f"""Existing term mappings (learn the patterns):
{examples}

Suggest mappings for these new terms:
{terms_list}

Return ONLY a valid JSON object like: {{"Term1": "replacement1", "Term2": null, ...}}"""

    try:
        response = await ai_service.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=2000,
            temperature=0.2,
        )

        # Parse JSON response
        start = response.find("{")
        end = response.rfind("}") + 1

        if start >= 0 and end > start:
            suggestions = json.loads(response[start:end])
            return suggestions

        return {term: None for term in terms}

    except Exception:
        return {term: None for term in terms}


def find_term_contexts(document_text: str, term: str, max_contexts: int = 3) -> list[str]:
    """
    Find sentences/paragraphs containing a specific term.

    Args:
        document_text: The document text to search
        term: The term to find contexts for
        max_contexts: Maximum number of contexts to return

    Returns:
        List of context strings containing the term
    """
    contexts = []

    # Split into sentences (simple approach)
    sentences = re.split(r'(?<=[.!?])\s+', document_text)

    # Escape special regex characters in term
    escaped_term = re.escape(term)
    pattern = re.compile(rf'\b{escaped_term}\b', re.IGNORECASE)

    for sentence in sentences:
        if pattern.search(sentence):
            # Clean up the sentence
            clean_sentence = sentence.strip()
            if len(clean_sentence) > 20:  # Skip very short matches
                contexts.append(clean_sentence)
                if len(contexts) >= max_contexts:
                    break

    return contexts
