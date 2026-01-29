"""AI service for text processing, embeddings, and generation."""

from abc import ABC, abstractmethod
from typing import Any

import anthropic
import openai

from app.config import get_settings
from app.core.exceptions import AIServiceError

settings = get_settings()


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        """Generate text from a prompt."""
        pass

    @abstractmethod
    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""
        pass

    @abstractmethod
    async def summarize(self, text: str, max_length: int = 500) -> str:
        """Summarize text."""
        pass


class OpenAIProvider(AIProvider):
    """OpenAI API provider."""

    def __init__(self, api_key: str) -> None:
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.embedding_model = settings.embedding_model
        self.chat_model = "gpt-4o"

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await self.client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except openai.APIError as e:
            raise AIServiceError(f"OpenAI API error: {e}") from e

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except openai.APIError as e:
            raise AIServiceError(f"OpenAI embedding error: {e}") from e

    async def summarize(self, text: str, max_length: int = 500) -> str:
        system_prompt = (
            "You are a document summarization assistant. "
            "Create concise, informative summaries that capture the key points."
        )
        prompt = f"Summarize the following text in approximately {max_length} characters:\n\n{text}"
        return await self.generate_text(prompt, system_prompt, max_tokens=max_length // 2)


class AnthropicProvider(AIProvider):
    """Anthropic Claude API provider."""

    def __init__(self, api_key: str) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            response = await self.client.messages.create(**kwargs)
            return response.content[0].text if response.content else ""
        except anthropic.APIError as e:
            raise AIServiceError(f"Anthropic API error: {e}") from e

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        # Anthropic doesn't have a native embedding API, fall back to OpenAI
        if not settings.openai_api_key:
            raise AIServiceError("OpenAI API key required for embeddings with Anthropic provider")
        openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            response = await openai_client.embeddings.create(
                model=settings.embedding_model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except openai.APIError as e:
            raise AIServiceError(f"Embedding generation error: {e}") from e

    async def summarize(self, text: str, max_length: int = 500) -> str:
        system_prompt = (
            "You are a document summarization assistant. "
            "Create concise, informative summaries that capture the key points."
        )
        prompt = f"Summarize the following text in approximately {max_length} characters:\n\n{text}"
        return await self.generate_text(prompt, system_prompt, max_tokens=max_length // 2)


class AIService:
    """Main AI service that uses configured provider."""

    def __init__(self) -> None:
        self.provider: AIProvider | None = None
        self._initialize_provider()

    def _initialize_provider(self) -> None:
        if settings.default_ai_provider == "anthropic" and settings.anthropic_api_key:
            self.provider = AnthropicProvider(settings.anthropic_api_key)
        elif settings.openai_api_key:
            self.provider = OpenAIProvider(settings.openai_api_key)
        # Provider remains None if no API keys configured

    def _ensure_provider(self) -> AIProvider:
        if self.provider is None:
            raise AIServiceError("No AI provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY")
        return self.provider

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        """Generate text from a prompt."""
        provider = self._ensure_provider()
        return await provider.generate_text(prompt, system_prompt, max_tokens, temperature)

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""
        provider = self._ensure_provider()
        return await provider.generate_embeddings(texts)

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        embeddings = await self.generate_embeddings([text])
        return embeddings[0]

    async def summarize_document(self, text: str, max_length: int = 500) -> str:
        """Summarize a document."""
        provider = self._ensure_provider()
        return await provider.summarize(text, max_length)

    async def answer_question(
        self,
        question: str,
        context: list[str],
        system_prompt: str | None = None,
    ) -> str:
        """Answer a question based on provided context."""
        provider = self._ensure_provider()
        context_text = "\n\n---\n\n".join(context)
        default_system = (
            "You are a helpful assistant that answers questions based on the provided context. "
            "Only use information from the context to answer. If the context doesn't contain "
            "enough information to answer, say so clearly."
        )
        prompt = f"Context:\n{context_text}\n\nQuestion: {question}\n\nAnswer:"
        return await provider.generate_text(
            prompt,
            system_prompt or default_system,
            max_tokens=1000,
            temperature=0.3,
        )

    async def extract_metadata(self, text: str) -> dict[str, Any]:
        """Extract metadata from document text."""
        provider = self._ensure_provider()
        system_prompt = (
            "You are a document analysis assistant. Extract key metadata from documents. "
            "Return a JSON object with relevant fields like: title, author, date, topics, "
            "key_entities, language, document_type. Only include fields that can be determined "
            "from the text."
        )
        prompt = f"Extract metadata from this document:\n\n{text[:5000]}"
        response = await provider.generate_text(prompt, system_prompt, max_tokens=500, temperature=0.1)

        # Parse JSON response
        import json
        try:
            # Try to extract JSON from response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass
        return {"raw_response": response}

    def is_configured(self) -> bool:
        """Check if AI service is configured."""
        return self.provider is not None


_ai_service_instance: AIService | None = None


def get_ai_service() -> AIService:
    """Get AI service singleton instance."""
    global _ai_service_instance
    if _ai_service_instance is None:
        _ai_service_instance = AIService()
    return _ai_service_instance
