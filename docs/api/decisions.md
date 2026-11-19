# Decisiones de personas (2.0.0)

Las reglas y la IA se equivocan; una persona que conoce los documentos puede corregirlas. Una
`ClassificationDecision` dice qué decidió alguien sobre un documento, y `ContextBuilder.build` la aplica en cada
construcción.

| Acción | Qué hace | `axes` |
|---|---|---|
| `set_axis` | Fija los valores de un eje | Un eje: `{"domains": ["seguridad"]}` |
| `confirm` | Da por buena la clasificación del documento | Todos sus ejes, con los valores confirmados |
| `exclude` | Saca el documento del contexto (ni dominios, ni sitio, ni reorganización) | Ninguno |
| `set_current_version` | Marca el documento como la versión vigente de su grupo ([versiones](versions.md)); se aplica también sin manifiesto | Ninguno |

En un eje que organiza (carpeta o subcarpeta) va exactamente un valor. En un eje que solo etiqueta, una lista vacía
significa «ninguno» y la IA ya no lo rellena.

```python
from doc_organize import ClassificationDecision, ClassificationDecisionStore

store = ClassificationDecisionStore(project.root_path)
await store.add(ClassificationDecision(
    document_key="ENS/politica_seguridad.pdf",   # ruta relativa a la raíz de escaneo
    source_sha256=sha,                           # huella del original al decidir
    action="set_axis",
    axes={"domains": ["seguridad-informacion"]},
    author="ana",
    reason="Es la política del SGSI, no de calidad",
))
context = await ContextBuilder().build(project, documents, taxonomy_manifest=manifest, scan_roots=["/mnt/entrada"])
```

## Cómo se aplican

- **Después de las reglas y antes de la IA**: lo decidido queda con `classified_by="human"` y confianza 1, el documento
  cambia de dominio si se decidió su carpeta, y la IA no pregunta por los ejes decididos. Lo no decidido sigue
  saliendo de las reglas y la IA.
- Solo con manifiesto de taxonomía; sin él, las decisiones quedan en `Context.stale_decisions` con `no_manifest`.
- `build(decisions=True)` (por defecto) usa las del proyecto, `decisions=False` ninguna, o se pasa una lista.
- Los documentos se identifican por su ruta relativa a la raíz de escaneo (`scan_roots`; por defecto, la carpeta común
  de todos los originales), como en la [evaluación](evaluation.md).

Una decisión que no se puede aplicar no rompe la construcción: queda en el contexto para revisarla.

| Dónde | `reason` | Por qué |
|---|---|---|
| `stale_decisions` | `source_changed` | El original cambió desde la decisión (`source_sha256` distinto; sin huella, vale para cualquier versión) |
| `stale_decisions` | `unknown_axis` / `unknown_value` | El eje o el valor ya no están en el catálogo, o un eje que organiza no tiene exactamente un valor |
| `stale_decisions` | `no_manifest` | Construcción sin manifiesto |
| `orphan_decisions` | `missing_document` | El documento no está en la construcción (o no tiene conversión y la decisión no es `exclude`) |

`Context.decisions_applied` cuenta las aplicadas y `Context.excluded_documents` lista los originales excluidos.

## El almacén

`ClassificationDecisionStore(project_root)` guarda las decisiones en `<raíz>/.doc_organize/decisions.json`, con
escritura atómica y bloqueo entre procesos. Una decisión nueva sustituye a las que decidían lo mismo, que pasan al
historial (`revoked()`, con `revoke_reason="replaced"`). Un `confirm` o un `exclude` sustituyen todo lo del documento;
un `set_axis`, lo del mismo eje y un `exclude`. Un `confirm` anterior se conserva y el `set_axis` gana en su eje.
`revoke(id, author=, reason=)` retira una decisión.

## Referencia a partir de decisiones

`gold_from_decisions(decisions)` convierte los `confirm` y `set_axis` en una referencia para
[`evaluate_classification`](evaluation.md): lo que decidieron las personas es la clasificación correcta.

## Cola de revisión

`review_queue(context, *, roots=None)` dice qué documentos debería mirar una persona y por qué, sin cambiar nada. Cada
`ReviewItem` trae la clave del documento (la de las decisiones), el eje y el valor afectados, su confianza y una
explicación, ordenado por prioridad:

| Prioridad | `reason` | Cuándo |
|---|---|---|
| 0 | `stale_decision` | Una decisión no se aplicó (original o catálogo cambiados) |
| 1 | `unclassified` | Sin conversión, o con el eje que organiza en carpeta vacío |
| 2 | `rules_ai_disagreement` | La IA propuso otro dominio que el que quedó |
| 3 | `unverified_evidence` | La cita de la IA no aparece en el documento (su confianza quedó bajo el umbral) |
| 4 | `low_confidence` | Un valor por debajo del umbral de su eje |
| 5 | `unconfirmed_version` | Un grupo de versiones cuya vigente no ha confirmado nadie |

Lo que decidió una persona (`classified_by="human"`) no vuelve a la cola. Al resolver un elemento con una decisión
(`ClassificationDecisionStore.add`), desaparece en la siguiente construcción.

::: doc_organize.context.review_queue
    options:
      show_root_heading: false
      members:
        - review_queue
        - ReviewItem

::: doc_organize.context.decisions
    options:
      show_root_heading: false
      members:
        - ClassificationDecisionStore
        - gold_from_decisions

::: doc_organize.core.models
    options:
      show_root_heading: false
      members:
        - ClassificationDecision
        - DecisionIssue
