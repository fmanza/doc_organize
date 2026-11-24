# Ejemplo: Clasificación Semántica con Embeddings

**Objetivo**: Demostrar cómo `ContextBuilder.build(semantic=True)` rellena con embeddings los ejes que las reglas dejan
vacíos, qué ejemplos y qué preselección recibe la IA para lo que queda, y cómo el índice de embeddings evita volver a
pedir vectores.

## 1. Contexto del Ejemplo

Las reglas buscan palabras: un documento que habla de «suministradores» no encaja en una entrada cuyas palabras clave
son «proveedor» y «homologacion». La sub-fase semántica compara significados: un vector por documento y uno por valor
del catálogo, y asigna el valor más parecido si llega al umbral. Lo que siga vacío va a la IA, que recibe como ejemplos
los documentos parecidos ya clasificados con fiabilidad y, en los ejes de más de 25 valores, solo los 15 más parecidos.

El ejemplo construye el contexto de cinco documentos escritos a mano (original, `.md` y `.json`, como en
[Construir el contexto](context-build.md)) con un manifiesto de tres ejes: dominios, tipos de material y un eje de
etiqueta `normas` de 26 valores con `rules: false` (solo lo rellenan los embeddings y la IA). Después reconstruye con el
índice ya guardado y lo borra.

### Requisitos

- Python 3.12+
- `doc_organize[ai,context]` instalado (`httpx` para el cliente de IA, PyYAML para el manifiesto)

No hay red, ni Docling, ni modelo: el proxy LiteLLM es falso (`httpx.MockTransport`). Sus embeddings son vectores de
cuatro números que cuentan raíces de palabras por «concepto», y su clasificación es una respuesta fija: **las respuestas
del modelo son simuladas**. Con un modelo de embeddings real los vectores, las similitudes y por tanto lo asignado
variarán. La clave `sk-ejemplo` es ficticia.

## 2. Implementación de Referencia

```python
import asyncio
import json
import tempfile

from pathlib import Path

import httpx

from doc_organize import (
    AiSettings,
    ContextBuilder,
    ConversionResult,
    LlmClient,
    Project,
    clear_embedding_index,
    embedding_index_info,
    parse_taxonomy_template,
)

NORMS = "\n".join(f"  - slug: ni-{n:02d}\n    name: Norma interna NI-{n:02d}" for n in range(1, 25))
MANIFEST = f"""\
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
    description: Compras y homologación de proveedores
    keywords: [proveedor, homologacion]
  - slug: mejora-continua
    name: Mejora Continua
    description: No conformidades, incidencias y acciones correctivas
    keywords: [no conformidad, accion correctiva]
- key: material_types
  name: Tipos de material
  organizes: subfolder
  entries:
  - slug: procedimiento
    name: Procedimiento
  - slug: registro
    name: Registro
- key: normas
  name: Normas internas
  multiple: true
  rules: false
  entries:
{NORMS}
  - slug: ni-25
    name: Norma interna NI-25
    description: Evaluación de suministradores
  - slug: ni-26
    name: Norma interna NI-26
    description: Tratamiento de incidencias y reclamaciones
---
"""

# Embeddings falsos y deterministas: una dimensión por «concepto»: cuántas de sus raíces aparecen
CONCEPTS = [
    ("proveedor", "suministrador", "homolog", "compra"),
    ("conformidad", "correctiv", "incidencia", "reclamaci"),
    ("procedimiento", "pasos"),
    ("registro", "acta"),
]
embedded: list[str] = []  # Cada texto que llega al «proxy» para embeber
asked: list[dict] = []  # Cada petición de clasificación (tarea `classify`)


def fake_vector(text: str) -> list[float]:
    lowered = text.lower()
    return [float(sum(lowered.count(root) for root in roots)) for roots in CONCEPTS]


def fake_proxy(request: httpx.Request) -> httpx.Response:
    """LiteLLM Proxy falso: `/embeddings` con `fake_vector` y `/chat/completions` con una clasificación fija."""
    body = json.loads(request.content)
    if request.url.path.endswith("/embeddings"):
        embedded.extend(body["input"])
        data = [{"index": i, "embedding": fake_vector(text)} for i, text in enumerate(body["input"])]
        return httpx.Response(200, json={"data": data, "model": "proveedor/embed-falso"})
    asked.append(body)
    schema = body["response_format"]["json_schema"]["schema"]
    wanted = {"domains": "mejora-continua", "material_types": "registro", "normas": "ni-26"}  # Respuesta simulada
    answer: dict = {"reasoning": "Respuesta simulada"}
    for key in schema["required"]:
        if key != "reasoning":
            allowed = schema["properties"][key]["properties"]["values"]["items"]["properties"]["value"]["enum"]
            answer[key] = {"values": [{"value": wanted[key], "confidence": 0.9, "evidence": None}] if wanted[key] in allowed else []}
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 300, "completion_tokens": 40}}
    )


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
                "calidad/nc-04.txt",
                "Registro de no conformidad 04",
                "Registro de la no conformidad detectada y de la accion correctiva acordada.",
            ),
            converted(
                root,
                "compras/evaluacion.txt",
                "Evaluación anual de suministradores",
                "Procedimiento: pasos para puntuar a cada suministrador por plazo y calidad de las compras.",
            ),
            converted(
                root,
                "varios/reclamacion.txt",
                "Reclamación 12",
                "Acta de la reclamación del cliente por un pedido de un suministrador: incidencia abierta.",
            ),
            converted(
                root,
                "varios/auditoria.txt",
                "Informe de auditoría",
                "Auditoría a un suministrador: se abre una incidencia, se levanta acta y se revisa el procedimiento.",
            ),
        ]
        manifest = parse_taxonomy_template(MANIFEST)
        settings = AiSettings(base_url="https://proxy.invalid", virtual_key="sk-ejemplo")

        async with LlmClient(settings, transport=httpx.MockTransport(fake_proxy)) as llm:
            context = await ContextBuilder().build(
                project,
                documents,
                taxonomy_manifest=manifest,
                decisions=False,
                llm=llm,
                semantic=True,
                semantic_threshold=0.75,
                ai_scope="missing_axes",
            )
            print("== Primera construcción")
            for domain in context.domains:
                for document in domain.documents:
                    values = {
                        key: [(v.slug, round(v.confidence, 2), v.classified_by) for v in axis] for key, axis in document.classification.axes.items()
                    }
                    print(f"{Path(document.source_path).name}: {values}")
            print(f"Semántica: {context.ai_stats.semantic_classification.model_dump(include={'sent', 'cached', 'assigned', 'failed'})}")
            print(f"IA: enviados={context.ai_stats.classification.sent} asignados={context.ai_stats.classification.assigned}")
            print(f"Textos embebidos: {len(embedded)}; p. ej. {embedded[0]!r}")
            for body in asked:
                user = next(m["content"] for m in body["messages"] if m["role"] == "user")
                title = next(line for line in user.splitlines() if line.startswith("Título:"))
                print(f"== A la IA: {title}")
                print("\n".join(line for line in user.splitlines() if line.startswith(("Documentos parecidos", "- «"))))
                props = body["response_format"]["json_schema"]["schema"]["properties"]
                enums = {
                    key: value["properties"]["values"]["items"]["properties"]["value"]["enum"] for key, value in props.items() if key != "reasoning"
                }
                print(f"Valores por eje en el esquema: { ({key: len(values) for key, values in enums.items()}) }")
                if "normas" in enums:
                    left_out = [entry.slug for entry in manifest.axis("normas").entries if entry.slug not in enums["normas"]]
                    print(
                        f"  normas fuera de la preselección: {left_out}; ¿van ni-25 y ni-26? {'ni-25' in enums['normas'] and 'ni-26' in enums['normas']}"
                    )
            print(f"Índice: {[(i.model, i.vectors, i.dimension) for i in embedding_index_info(root)]}")

            embedded.clear()
            asked.clear()
            again = await ContextBuilder().build(
                project,
                documents,
                taxonomy_manifest=manifest,
                decisions=False,
                llm=llm,
                semantic=True,
                ai_scope="missing_axes",
            )
            print("== Segunda construcción (mismo índice)")
            print(
                f"Semántica: {again.ai_stats.semantic_classification.model_dump(include={'sent', 'cached', 'assigned'})}; textos embebidos={len(embedded)}"
            )
            print(f"Índices borrados: {clear_embedding_index(root)}; quedan {embedding_index_info(root)}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Orden de las fases**: `build(llm=..., semantic=True, ai_scope="missing_axes")` clasifica primero por reglas (y
   decisiones, aquí `decisions=False`), después rellena con embeddings los ejes vacíos y por último pregunta a la IA
   lo que siga vacío. `semantic=True` exige `llm` (si no, `ValueError`) y un manifiesto. `missing_axes` hace que la IA
   vea también los ejes de etiqueta vacíos (con `unclassified`, solo los que organizan)
2. **Qué se embebe**: cada valor del catálogo como `«Eje: Nombre. Descripción. palabras clave»` (la primera línea de
   «Textos embebidos») y el extracto de cada documento con algún eje vacío. Se piden con la tarea `embed` de
   `AiSettings` (aquí, el alias por defecto `doc-organize-embed`)
3. **Lo que rellena la semántica** (`classified_by="semantic"`, con la similitud como confianza):
    - `evaluacion.txt`: las reglas no lo cubrían («suministradores» no es ninguna palabra clave); la semántica lo lleva
      a `gestion-proveedores` (0,89)
    - `reclamacion.txt`: dominio `mejora-continua` (0,9)
    - `normas` de los cuatro primeros: el valor que llega al umbral (0,75). Es un eje de varios valores, así que se
      asignan todos los que llegan, hasta 5
    - nunca cambia lo que asignaron las reglas: `alta.txt` y `nc-04.txt` conservan su dominio por reglas (este, con
      0,5), porque la semántica solo mira los ejes vacíos
4. **Lo que no decide**: en `auditoria.txt` el dominio empata (una raíz de cada concepto) y un eje de un valor necesita
   que el mejor le saque `SEMANTIC_MARGIN` (0,03) al segundo; sus `normas` se quedan en 0,5, por debajo del umbral.
   Va a la IA, igual que el tipo de material de `reclamacion.txt` (la IA recibe los dos ejes que organizan si falta
   alguno, pero solo rellena el vacío)
5. **Ejemplos para la IA** (`ai_examples`, 3 por defecto): van en el mensaje `user`, antes del documento, con los ejes
   que se le piden. Sirven de ejemplo los documentos con un valor decidido por una persona o con confianza de al menos
   0,9 en un eje que organiza, por quien sea: por eso «Informe de auditoría» (tipo de material por reglas, 1,0) es
   ejemplo de «Reclamación 12» aunque su dominio también esté pendiente, y solo aporta `material_types`. Un documento
   nunca es su propio ejemplo, ni un duplicado suyo, ni uno de `example_exclusions`
6. **Preselección**: `normas` tiene 26 valores (más de `PRESELECT_MIN_ENTRIES`, 25), así que al modelo solo van los 15
   más parecidos al documento, en el prompt y en el `enum` del esquema. `ni-25` y `ni-26` son los únicos con similitud;
   los demás empatan a 0 y quedan en el orden del catálogo, así que salen `ni-14` a `ni-24`. Los ejes de 25 valores o
   menos (aquí `domains` y `material_types`) van enteros
7. **El índice**: `embedding_index_info` dice que hay un índice del modelo `doc-organize-embed` con 35 vectores (30
   valores del catálogo y 5 extractos) de dimensión 4. La segunda construcción no pide ningún vector (`sent=0`,
   `cached=35`) y asigna lo mismo. `clear_embedding_index` lo borra (devuelve cuántos índices); la siguiente
   construcción con `semantic=True` volvería a pedirlos
8. **Estadísticas**: `context.ai_stats.semantic_classification` cuenta textos embebidos (`sent`), sacados del índice
   (`cached`), documentos con algún eje asignado (`assigned`) y fallos del modelo de embeddings (`failed`: un fallo no
   para la construcción)

## 4. Ejecución y Pruebas

```bash
$ python semantic_example.py
== Primera construcción
alta.txt: {'domains': [('gestion-proveedores', 0.75, 'rules')], 'material_types': [('procedimiento', 1.0, 'rules')], 'normas': [('ni-25', 0.93, 'semantic')]}
evaluacion.txt: {'domains': [('gestion-proveedores', 0.89, 'semantic')], 'material_types': [('procedimiento', 1.0, 'rules')], 'normas': [('ni-25', 0.89, 'semantic')]}
nc-04.txt: {'domains': [('mejora-continua', 0.5, 'rules')], 'material_types': [('registro', 1.0, 'rules')], 'normas': [('ni-26', 0.83, 'semantic')]}
reclamacion.txt: {'domains': [('mejora-continua', 0.9, 'semantic')], 'material_types': [('registro', 0.9, 'ai')], 'normas': [('ni-26', 0.9, 'semantic')]}
auditoria.txt: {'domains': [('mejora-continua', 0.9, 'ai')], 'material_types': [('procedimiento', 1.0, 'rules')], 'normas': [('ni-26', 0.9, 'ai')]}
Semántica: {'sent': 35, 'assigned': 4, 'failed': 0, 'cached': 0}
IA: enviados=2 asignados=2
Textos embebidos: 35; p. ej. 'Dominios: Gestión de Proveedores. Compras y homologación de proveedores. proveedor, homologacion'
== A la IA: Título: Reclamación 12
Documentos parecidos ya clasificados (orientativo):
- «Registro de no conformidad 04» → domains: mejora-continua; material_types: registro
- «Informe de auditoría» → material_types: procedimiento
- «Procedimiento de homologación de proveedores» → domains: gestion-proveedores; material_types: procedimiento
Valores por eje en el esquema: {'domains': 2, 'material_types': 2}
== A la IA: Título: Informe de auditoría
Documentos parecidos ya clasificados (orientativo):
- «Reclamación 12» → domains: mejora-continua; normas: ni-26
- «Registro de no conformidad 04» → domains: mejora-continua; material_types: registro; normas: ni-26
- «Evaluación anual de suministradores» → domains: gestion-proveedores; material_types: procedimiento; normas: ni-25
Valores por eje en el esquema: {'domains': 2, 'material_types': 2, 'normas': 15}
  normas fuera de la preselección: ['ni-14', 'ni-15', 'ni-16', 'ni-17', 'ni-18', 'ni-19', 'ni-20', 'ni-21', 'ni-22', 'ni-23', 'ni-24']; ¿van ni-25 y ni-26? True
Índice: [('doc-organize-embed', 35, 4)]
== Segunda construcción (mismo índice)
Semántica: {'sent': 0, 'assigned': 4, 'cached': 35}; textos embebidos=0
Índices borrados: 1; quedan []
```

La salida es estable porque los vectores y las respuestas los da el proxy falso. Validación sintáctica:
`python -m py_compile semantic_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Clasificación semántica](../api/semantic.md)
- [Documentación funcional: Contexto](../functional/context.md)
- [Ejemplo: Construir el contexto](context-build.md) (las mismas piezas, solo con reglas)
- [Ejemplo: Cliente de IA sin red](llm-client.md) (`LlmClient.embed` sobre `MockTransport`)
- [Ejemplo: Agentes que proponen](agents.md)
