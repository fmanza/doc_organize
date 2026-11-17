"""
Detección y redacción de credenciales en el texto de los documentos (1.7.0, F1 del plan de 2.0.0).

Los documentos de oficina llevan a veces contraseñas, tokens o un ``client_secret`` en claro (anexos técnicos, actas
con accesos). Antes de que su texto salga de la aplicación (hacia un servicio de IA) o se publique (sitio del
contexto), el **valor** se sustituye por ``«REDACTADO»``. Adaptado de ``doc_ia/scripts/redact_credentials.py``.

* Solo se sustituye el valor, nunca la clave: el texto sigue diciendo que había una contraseña y dónde.
* No se tocan marcadores evidentes (``xxxxxx``, ``***``, ``<…>``, ``${VAR}``), URL ni valores ya redactados: es
  idempotente. En las reglas por palabra clave (``client_secret``, ``password``, ``token``) el valor debe tener algún
  carácter que no sea letra (descarta «Contraseña: obligatoria»); **una contraseña solo de letras no se detecta**.
* Los hallazgos dan línea y regla, **nunca el valor**.
* Es una red de seguridad, no una garantía.

Funciones puras, sin E/S ni dependencias: las usan ``ContextBuilder``, ``TaxonomyManifestDraftClient`` y
``SiteGenerator``, y cualquier consumidor que envíe texto fuera.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Final

#: Lo que sustituye a cada valor. Sin ``<``/``>``: en Markdown se tomaría por una etiqueta HTML y no se vería.
REDACTED: Final = "«REDACTADO»"

# Separador entre clave y valor: «=», «:» o «(» con negritas, comillas o espacios de Markdown.
_SEP = r"\s*[=:(]\s*[*`\"']*\s*"
# Guion bajo que docling escapa en Markdown (``client\_secret``).
_US = r"\\?_"
# Valor: sin espacios ni delimitadores de URL, tabla o Markdown.
_VALUE = r"([^\s&*`\"'<>|),;\[\]]{%d,})"
# Reglas por palabra clave en las que una palabra corriente («obligatoria», «Bearer») no es secreto.
_NEEDS_NON_LETTER: Final = frozenset({"client_secret", "password", "token"})


@dataclass(frozen=True)
class _Rule:
    name: str
    pattern: re.Pattern[str]


_RULES: Final[tuple[_Rule, ...]] = (
    _Rule(
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    ),
    _Rule("client_secret", re.compile(rf"(?i)client{_US}secret{_SEP}(?P<value>{_VALUE % 8})")),
    _Rule(
        "password",
        re.compile(rf"(?i)\b(?:password|passwd|pwd|pass|contraseña|clave){_SEP}(?P<value>{_VALUE % 6})"),
    ),
    _Rule(
        "token",
        re.compile(rf"(?i)\b(?:(?:access|refresh|id){_US})?(?:token|api{_US}?key|apikey|secret){_SEP}(?P<value>{_VALUE % 16})"),
    ),
    _Rule("url_basic_auth", re.compile(r"://[^/\s:@]+:(?P<value>[^@\s/]{3,})@")),
    _Rule("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    _Rule("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    _Rule("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    _Rule("api_key_sk", re.compile(r"\bsk-(?:[A-Za-z0-9_-]{4,}-)?[A-Za-z0-9]{20,}\b")),
)

#: Reglas que aplica ``scan_credentials`` (para documentar y para los recuentos por regla).
CREDENTIAL_RULES: Final[tuple[str, ...]] = tuple(rule.name for rule in _RULES)

# Marcadores que no son un secreto: x/*/./- repetidos, <…>, {…}, ${VAR}, $VAR.
_PLACEHOLDER = re.compile(r"^(?:[xX*.\-_]+|<[^>]*>|\{[^}]*\}|\$\{?[\w.]+\}?)$")


@dataclass(frozen=True)
class CredentialFinding:
    """Credencial encontrada, **sin su valor**.

    Attributes:
        line (int): Línea (desde 1) del texto original.
        rule (str): Regla que la detectó (una de ``CREDENTIAL_RULES``).
    """

    line: int
    rule: str


@dataclass(frozen=True)
class RedactionResult:
    """Texto con los valores sustituidos por ``REDACTED`` y lo que se encontró.

    Attributes:
        text (str): Texto redactado (igual al original si no había nada).
        findings (tuple[CredentialFinding, ...]): Hallazgos, en orden de aparición.
    """

    text: str
    findings: tuple[CredentialFinding, ...]


def _is_placeholder(value: str) -> bool:
    """Marcador, valor ya redactado o URL (``Token url: https://…`` describe un endpoint)."""
    return bool(_PLACEHOLDER.match(value)) or REDACTED in value or "://" in value or value.lower().startswith("http")


def _spans(text: str) -> list[tuple[int, int, str]]:
    """Tramos ``(inicio, fin, regla)`` a redactar, sin solapes, en orden de aparición."""
    found: list[tuple[int, int, str]] = []
    for rule in _RULES:
        for match in rule.pattern.finditer(text):
            if "value" in rule.pattern.groupindex:
                value = match.group("value")
                if _is_placeholder(value) or (rule.name in _NEEDS_NON_LETTER and value.isalpha()):
                    continue
                start, end = match.span("value")
            else:
                if REDACTED in match.group(0):
                    continue
                start, end = match.span()
            found.append((start, end, rule.name))
    found.sort()
    spans: list[tuple[int, int, str]] = []
    for start, end, name in found:
        if spans and start < spans[-1][1]:  # solapa con un tramo anterior (p. ej. un JWT dentro de un token)
            continue
        spans.append((start, end, name))
    return spans


def scan_credentials(text: str) -> list[CredentialFinding]:
    """Credenciales de ``text``: línea y regla de cada una, nunca el valor.

    Example:
        >>> scan_credentials("usuario: ana\\npassword: S3cret!42")
        [CredentialFinding(line=2, rule='password')]
        >>> scan_credentials("Contraseña: obligatoria")
        []
    """
    return [CredentialFinding(text.count("\n", 0, start) + 1, name) for start, _, name in _spans(text)]


def redact_credentials(text: str) -> RedactionResult:
    """``text`` con el valor de cada credencial sustituido por ``REDACTED`` (la clave se conserva). Idempotente.

    Example:
        >>> result = redact_credentials("password: S3cret!42 y client_secret=abcd1234efgh")
        >>> result.text
        'password: «REDACTADO» y client_secret=«REDACTADO»'
        >>> tuple(finding.rule for finding in result.findings)
        ('password', 'client_secret')
        >>> redact_credentials(result.text).findings
        ()
    """
    spans = _spans(text)
    findings = tuple(CredentialFinding(text.count("\n", 0, start) + 1, name) for start, _, name in spans)
    for start, end, _ in reversed(spans):
        text = text[:start] + REDACTED + text[end:]
    return RedactionResult(text=text, findings=findings)


__all__ = ["CREDENTIAL_RULES", "REDACTED", "CredentialFinding", "RedactionResult", "redact_credentials", "scan_credentials"]
