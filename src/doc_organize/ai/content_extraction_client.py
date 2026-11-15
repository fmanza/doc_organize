"""Cliente de IA para extracción de contenido: descripción y palabras clave (FASE 2)."""

import json
from dataclasses import dataclass
from typing import Any

from doc_organize.utils.logging import get_logger

_logger = get_logger(__name__)


@dataclass
class ContentExtractionClientConfig:
    """Configuración del cliente de extracción de contenido."""

    base_url: str
    virtual_key: str
    model: str = "claude-content-extractor"
    max_keywords: int = 5
    timeout_s: float = 30.0
    retries: int = 0
    retry_backoff_s: float = 0.5


class ContentExtractionResult:
    """Resultado de extracción de contenido."""

    def __init__(self, description: str | None = None, keywords: list[str] | None = None, confidence: float = 0.0):
        self.description = description or ""
        self.keywords = keywords or []
        self.confidence = confidence


class ContentExtractionClient:
    """Cliente para extracción de descripción y palabras clave usando IA.

    Llamadas a LiteLLM Proxy para analizar el contenido convertido.
    """

    def __init__(self, config: ContentExtractionClientConfig):
        """Inicializa el cliente.

        Args:
            config: Configuración del proxy y parámetros
        """
        self.config = config
        self.model = config.model
        self.max_keywords = config.max_keywords

    async def extract_content_metadata(
        self,
        markdown_content: str,
        document_type: str = "document",
        max_tokens: int = 500,
    ) -> ContentExtractionResult:
        """Extrae descripción y palabras clave del contenido convertido.

        Args:
            markdown_content: Contenido Markdown del documento (primeros 2000 caracteres)
            document_type: Tipo de documento para contexto (pdf, docx, etc.)
            max_tokens: Tokens máximos para la respuesta

        Returns:
            ContentExtractionResult con descripción, palabras clave y confianza

        Raises:
            httpx.RequestError: Error de conexión o timeout
            json.JSONDecodeError: Respuesta no es JSON válido
        """
        # Limitar contenido a 2000 caracteres
        content_sample = markdown_content[:2000]

        prompt = f"""Analiza este documento ({document_type}) y proporciona:
1. Una descripción de 1-2 líneas del contenido principal
2. Hasta {self.max_keywords} palabras clave principales (1-2 palabras cada una)

Responde ÚNICAMENTE en JSON válido sin comentarios adicionales:
{{"description": "...", "keywords": ["...", "..."]}}

Contenido del documento:
---
{content_sample}
---"""

        messages = [
            {
                "role": "user",
                "content": prompt,
            }
        ]

        try:
            response = await self._call_litellm(
                messages=messages,
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.3,  # Más determinístico
            )

            # Intentar parsear JSON
            try:
                # Limpiar respuesta de posibles envolturas
                cleaned = response.strip()
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json")[1].split("```")[0]
                elif "```" in cleaned:
                    cleaned = cleaned.split("```")[1].split("```")[0]

                data = json.loads(cleaned)
                description = str(data.get("description", "")).strip()[:500]
                keywords = data.get("keywords", [])

                # Validar keywords
                if not isinstance(keywords, list):
                    keywords = []
                keywords = [str(k).strip() for k in keywords if k][:self.max_keywords]

                return ContentExtractionResult(
                    description=description,
                    keywords=keywords,
                    confidence=0.8,  # Confianza por defecto para IA
                )
            except json.JSONDecodeError as e:
                _logger.warning(f"Respuesta no es JSON válido: {e}. Respuesta: {response[:200]}")
                return ContentExtractionResult()

        except Exception as e:
            _logger.error(f"Error en extracción de contenido: {e}")
            raise

    async def _call_litellm(
        self, messages: list[dict[str, Any]], model: str, max_tokens: int = 500, temperature: float = 0.3
    ) -> str:
        """Llamada a LiteLLM Proxy.

        Args:
            messages: Mensajes en formato OpenAI
            model: Modelo a usar
            max_tokens: Tokens máximos
            temperature: Temperature para generación

        Returns:
            Texto de la respuesta (content del primer choice)
        """
        import httpx

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {
            "Authorization": f"Bearer {self.config.virtual_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"

        async with httpx.AsyncClient(timeout=self.config.timeout_s) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]


__all__ = ["ContentExtractionClient", "ContentExtractionClientConfig", "ContentExtractionResult"]
