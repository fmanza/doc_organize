# Ejemplo: Agentes que Proponen sin Aplicar

**Objetivo**: Demostrar cómo comprobar un manifiesto de taxonomía por reglas con `check_taxonomy_rules` (sin IA) y cómo
el diseñador `TaxonomyDesignAgent` prueba cambios con esas mismas reglas y devuelve una propuesta, sin escribir nada.

## 1. Contexto del Ejemplo

Antes de pedir nada a la IA conviene saber qué cubren las reglas de un manifiesto: qué documentos quedan sin valor, qué
palabras clave no aparecen en ningún documento y qué entrada se quedó cerca del umbral. `check_taxonomy_rules` lo
calcula sobre un `RulesCorpus` (los textos leídos una vez), igual que la fase de reglas de `ContextBuilder.build`.

El diseñador de la taxonomía es un agente: una conversación con el modelo (tarea `agent`) en la que el modelo pide
herramientas de solo lectura (ver el resumen, buscar y leer documentos, editar un **borrador en memoria** y comprobarlo
por reglas) hasta dar su respuesta. Devuelve una `TaxonomyDesignProposal`: el manifiesto propuesto, su informe y el de
partida, la justificación y la ejecución completa (`AgentRun`). Nunca la guarda: una persona la revisa y, si la acepta,
la guarda con `save_taxonomy_manifest`.

### Requisitos

- Python 3.12+
- `doc_organize[ai,context]` instalado (`httpx` para el cliente de IA, PyYAML para el manifiesto)

La primera parte no usa IA. En la segunda, el proxy LiteLLM es falso (`httpx.MockTransport`) y sigue un guion: en cada
llamada pide la siguiente herramienta de `SCRIPT`. **Las respuestas del modelo son simuladas**: un modelo real elegirá
sus propias herramientas, ediciones y justificación, y el resultado variará. No hay red ni Docling; la clave
`sk-ejemplo` y la contraseña del documento son ficticias.

## 2. Implementación de Referencia

```python
import asyncio
import hashlib
import json
import tempfile

from pathlib import Path

import httpx

from doc_organize import (
    AiSettings,
    ConversionResult,
    LlmClient,
    Project,
    RulesCorpus,
    TaxonomyDesignAgent,
    check_taxonomy_rules,
    save_taxonomy_manifest,
)

MANIFEST = """\
---
schema: 2
title: Calidad mínima
axes:
- key: domains
  name: Dominios
  organizes: folder
  entries:
  - slug: gestion-proveedores
    name: Gestión de Proveedores
    keywords: [proveedor, homologacion, auditoria de segunda parte]
  - slug: mejora-continua
    name: Mejora Continua
    keywords: [no conformidad, accion correctiva]
- key: material_types
  name: Tipos de material
  organizes: subfolder
  entries:
  - slug: procedimiento
    name: Procedimiento
  - slug: registro
    name: Registro
---
"""

# Lo que «decide» el modelo en cada llamada (respuestas simuladas: un modelo real elegirá otras herramientas)
SCRIPT = [
    ("overview", {}),
    ("read_document", {"key": "compras/evaluacion.txt"}),
    ("edit_draft", {"changes": [{"axis": "domains", "action": "update", "slug": "gestion-proveedores", "add_keywords": ["suministrador"]}]}),
    ("undo_edit", {}),
    ("edit_draft", {"changes": [{"axis": "domains", "action": "update", "slug": "gestion-proveedores", "keywords": ["proveedor", "suministrador"]}]}),
    (
        "finish",
        {
            "rationale": "Gestión de Proveedores pasa a usar «proveedor» y «suministrador»: «auditoria de segunda parte» "
            "no aparecía en ningún documento y bajaba la puntuación."
        },
    ),
]
sent: list[dict] = []  # Cada petición que llega al «proxy»


def fake_proxy(request: httpx.Request) -> httpx.Response:
    """LiteLLM Proxy falso: en cada llamada de la tarea `agent` pide la siguiente herramienta del guion."""
    body = json.loads(request.content)
    sent.append(body)
    name, arguments = SCRIPT[len(sent) - 1]
    call = {"id": f"call_{len(sent)}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
    message = {"role": "assistant", "content": None, "tool_calls": [call]}
    return httpx.Response(200, json={"choices": [{"message": message}], "usage": {"prompt_tokens": 900, "completion_tokens": 60}})


def converted(root: Path, relative: str, title: str, text: str) -> ConversionResult:
    """Un original en `origen/` y su `.md` + `.json` en `Conversión/`, como los deja `DocumentConverter`."""
    source = root / "origen" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    stem = Path(relative).stem
    markdown, json_path = root / "Conversión" / f"{stem}.md", root / "Conversión" / f"{stem}.json"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}, ensure_ascii=False), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown), json_path=str(json_path), success=True)


def snapshot(root: Path) -> dict[str, str]:
    """Huella de cada fichero del proyecto, para comprobar que el agente no escribe nada."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        documents = [
            converted(
                root,
                "compras/alta.txt",
                "Procedimiento de homologación de proveedores",
                "Procedimiento para dar de alta a un proveedor y revisar su homologacion anual.",
            ),
            converted(
                root,
                "compras/evaluacion.txt",
                "Evaluación anual de suministradores",
                "Registro de la puntuación de cada suministrador (proveedor homologado). Portal de compras: password=Sup3rS3creta!",
            ),
            converted(
                root,
                "calidad/nc-04.txt",
                "Registro de no conformidad 04",
                "Registro de la no conformidad detectada y de la accion correctiva acordada.",
            ),
            converted(
                root,
                "calidad/reclamacion.txt",
                "Registro de reclamación 12",
                "Registro de la reclamacion de un cliente, tratada como no conformidad.",
            ),
        ]
        manifest = await save_taxonomy_manifest(project, MANIFEST)  # El manifiesto del proyecto, en disco

        # 1. Comprobar el manifiesto por reglas: sin IA y sin escribir nada
        corpus = await RulesCorpus.load(documents)
        report = check_taxonomy_rules(manifest, corpus)
        print(report.to_markdown())
        domains = report.axis("domains")
        print(f"Sin cubrir: {domains.uncovered_examples}")
        print(f"Palabras clave sin uso: {domains.unused_keywords}")
        for key, near in domains.near_misses.items():
            print(f"Casi: {key} → {near.slug} ({near.score}) encaja {near.matched}")

        # 2. El diseñador propone una mejora contra un proxy falso
        before = snapshot(root)
        settings = AiSettings(base_url="https://proxy.invalid", virtual_key="sk-ejemplo")
        async with LlmClient(settings, transport=httpx.MockTransport(fake_proxy)) as llm:
            proposal = await TaxonomyDesignAgent(llm).propose(corpus, base=manifest, instructions="No añadas dominios nuevos")

        run = proposal.run
        print(f"\nstop_reason={run.stop_reason} pasos={len(run.steps)} tokens={run.total_tokens} ediciones={proposal.edits}")
        results = iter(json.loads(m["content"]) for m in run.messages if m["role"] == "tool")
        for step in run.steps:
            for call in step.tool_calls:
                result = next(results) if call.name != "finish" else {}
                seen = f" → mejora={result['improves_on_base']}, domains={result['now']['domains']}" if "improves_on_base" in result else ""
                print(f"  paso {step.index}: {call.name}{seen}")
        print(f"Herramientas ofrecidas: {[tool['function']['name'] for tool in sent[0]['tools']]}")
        print("Partida:\n" + proposal.base_report.to_markdown())
        print("Propuesta:\n" + proposal.report.to_markdown())
        print(f"¿Mejora? {proposal.improves}. Justificación: {proposal.rationale}")
        proposed = {entry.slug: entry.keywords for entry in proposal.manifest.folder_axis.entries}
        print(f"Palabras clave propuestas: {proposed}")
        print(f"Manifiesto original intacto: {[entry.keywords for entry in manifest.folder_axis.entries]}")
        print(f"¿Ha cambiado algún fichero del proyecto? {snapshot(root) != before}")
        print(f"¿Llegó la contraseña al proxy? {'Sup3rS3creta' in json.dumps(sent)}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Comprobar por reglas**: `RulesCorpus.load(documents)` lee el `.json` de cada documento una vez; las claves son
   rutas relativas a la carpeta común (`compras/evaluacion.txt`). `check_taxonomy_rules(manifest, corpus)` no guarda
   nada ni llama a la IA. En un eje que organiza, la puntuación de una entrada es la fracción de sus términos (palabras
   del slug y palabras clave) que aparecen en el documento, con umbral 0,5:
    - `domains` cubre 2 de 4: `evaluacion.txt` y `reclamacion.txt` se quedan sin dominio
    - `unused_keywords`: «auditoria de segunda parte» no aparece en ningún documento, y además baja la puntuación de
      `gestion-proveedores` (un término más que no encaja)
    - `near_misses`: la entrada que más se acercó en cada documento sin cubrir y los términos que encajan
      (`gestion-proveedores` con 0,2 por «proveedor»)
2. **El agente**: `TaxonomyDesignAgent(llm).propose(corpus, base=manifest, instructions=...)` reutiliza el corpus ya
   leído. El borrador empieza siendo `manifest`. El modelo recibe siete herramientas y `finish` (la respuesta final,
   con el esquema de la justificación)
3. **Los pasos** (`run.steps`, cada uno una llamada al modelo con las herramientas que pidió):
    - `overview` y `read_document`: mira el resumen y lee el documento sin cubrir
    - `edit_draft` con `add_keywords`: el informe que vuelve dice `mejora=False`; con seis términos, `evaluacion.txt`
      solo encaja en dos (0,33) y sigue sin cubrir
    - `undo_edit`: vuelve al de partida (no es idempotente, se puede repetir)
    - `edit_draft` con `keywords` (sustituye todas): sin la palabra clave que no se usa, `evaluacion.txt` encaja en
      dos de cuatro términos (0,5) y la cobertura sube a 3 de 4: `mejora=True`
    - `finish`: la justificación
4. **La propuesta**: `proposal.manifest` (el borrador al terminar), `proposal.report` frente a `proposal.base_report`,
   `proposal.improves` (`report.improves_on(base_report)`: ningún eje pierde cobertura ni gana conflictos y alguno
   mejora) y `proposal.edits` (1: la edición deshecha no cuenta). `proposal.markdown()` da el manifiesto como texto
   para revisarlo. `reclamacion.txt` sigue sin cubrir: el agente propone, y la persona decide si basta
5. **No aplica nada**: la huella de todos los ficheros del proyecto (originales, conversiones y `taxonomy_manifest.md`)
   es la misma antes y después, y el `manifest` de partida conserva sus palabras clave. Las herramientas solo leen y
   calculan en memoria
6. **Redacción**: `read_document` devolvió un texto con `password=...`, pero lo que llega al proxy pasa por
   `LlmClient`, que redacta credenciales: la contraseña no sale. `run.messages` guarda la conversación **antes** de
   redactar, para auditarla: trátala como el contenido de los documentos
7. **Topes**: el diseñador usa `DEFAULT_DESIGN_LIMITS` (30 pasos, 400 000 tokens, 40 herramientas). Al llegar a uno,
   o al cancelarse con un `CancelToken`, no lanza: `proposal.manifest` es `None`, `run.stop_reason` dice por qué y
   `proposal.draft` conserva el último borrador. Los tokens salen de `usage` del proxy (aquí, 960 por llamada)

El revisor de la clasificación (`ReviewAgent`) sigue el mismo principio sobre un `Context` y su cola de revisión: sus
`ReviewProposal` se aceptan convirtiéndolas en decisión (`to_decision`) y guardándolas; ver la
[referencia técnica](../api/agents.md#revisor-de-la-clasificacion).

## 4. Ejecución y Pruebas

```bash
$ python agents_example.py
| Eje | Documentos | Cobertura | Conflictos | Entradas vacías |
|---|---|---|---|---|
| domains | 4 | 50,0 % | 0 | 0 |
| material_types | 4 | 100,0 % | 0 | 0 |
Sin cubrir: ['compras/evaluacion.txt', 'calidad/reclamacion.txt']
Palabras clave sin uso: {'gestion-proveedores': ['auditoria de segunda parte']}
Casi: compras/evaluacion.txt → gestion-proveedores (0.2) encaja ['proveedor']
Casi: calidad/reclamacion.txt → mejora-continua (0.25) encaja ['no conformidad']

stop_reason=finished pasos=6 tokens=5760 ediciones=1
  paso 0: overview
  paso 1: read_document
  paso 2: edit_draft → mejora=False, domains={'coverage': 0.5, 'covered': 2, 'documents': 4, 'conflicts': 0}
  paso 3: undo_edit → mejora=False, domains={'coverage': 0.5, 'covered': 2, 'documents': 4, 'conflicts': 0}
  paso 4: edit_draft → mejora=True, domains={'coverage': 0.75, 'covered': 3, 'documents': 4, 'conflicts': 0}
  paso 5: finish
Herramientas ofrecidas: ['overview', 'search_documents', 'read_document', 'edit_draft', 'undo_edit', 'restore_best', 'set_draft', 'finish']
Partida:
| Eje | Documentos | Cobertura | Conflictos | Entradas vacías |
|---|---|---|---|---|
| domains | 4 | 50,0 % | 0 | 0 |
| material_types | 4 | 100,0 % | 0 | 0 |
Propuesta:
| Eje | Documentos | Cobertura | Conflictos | Entradas vacías |
|---|---|---|---|---|
| domains | 4 | 75,0 % | 0 | 0 |
| material_types | 4 | 100,0 % | 0 | 0 |
¿Mejora? True. Justificación: Gestión de Proveedores pasa a usar «proveedor» y «suministrador»: «auditoria de segunda parte» no aparecía en ningún documento y bajaba la puntuación.
Palabras clave propuestas: {'gestion-proveedores': ['proveedor', 'suministrador'], 'mejora-continua': ['no conformidad', 'accion correctiva']}
Manifiesto original intacto: [['proveedor', 'homologacion', 'auditoria de segunda parte'], ['no conformidad', 'accion correctiva']]
¿Ha cambiado algún fichero del proyecto? False
¿Llegó la contraseña al proxy? False
```

La salida es estable porque las respuestas las da el guion del proxy falso. Validación sintáctica:
`python -m py_compile agents_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Agentes](../api/agents.md)
- [Documentación funcional: Revisión de la clasificación](../functional/revision_clasificacion.md)
- [Ejemplo: Clasificación semántica con embeddings](semantic.md)
- [Ejemplo: Construir el contexto](context-build.md) (las mismas reglas, en una construcción)
- [Ejemplo: Decisiones de personas y cola de revisión](decisions-review.md) (donde acaba una propuesta aceptada)
- [Ejemplo: Cliente de IA sin red](llm-client.md) (`LlmClient` sobre `MockTransport`)
