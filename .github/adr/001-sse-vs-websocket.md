# ADR-001: Protocolo de Comunicación para Conversión Asincrónica

**Fecha**: 2026-08-27  
**Status**: ACEPTADO  
**Impacto**: Arquitectura Web + Client

---

## Contexto

La aplicación Doclink Extractor requiere notificar al cliente sobre el progreso de conversión de documentos en batch (10-1000 PDFs). El plan AUDIT identifica ambigüedad entre dos patrones:

- **Server-Sent Events (SSE)** — HTTP estándar, unidireccional servidor → cliente
- **WebSocket** — Protocolo full-duplex custom

Esta decisión impacta:
- Complejidad de implementación (servidor + cliente)
- Escalabilidad (conexiones simultáneas)
- Compatibilidad browser (IE11, Safari)
- Testing y observabilidad

---

## Opciones Consideradas

### Opción A: Server-Sent Events (SSE)

**Ventajas**:
- ✅ HTTP estándar (RFC 6585), compatible con proxies/load balancers
- ✅ Reconexión automática (built-in en EventSource API)
- ✅ Testing simple: httpx.stream() en pytest
- ✅ Stateless en servidor (escalable)
- ✅ Debugging: observable en DevTools Network tab como HTTP

**Desventajas**:
- ❌ Unidireccional (servidor → cliente) — no se puede enviar estado cliente
- ❌ Latencia ~200-500ms (HTTP polling)
- ❌ No IE11 nativo (requiere polyfill)
- ❌ Máx 6 conexiones/domain (HTTP/1.1 limit) sin domain sharding

**Performance**:
- Latencia: 200-500ms por evento
- Overhead: ~0.1ms/evento en servidor
- Conexiones simultáneas: ~1000-5000 con fastapi + uvicorn (4 workers)

### Opción B: WebSocket

**Ventajas**:
- ✅ Full-duplex (cliente ↔ servidor)
- ✅ Latencia baja: 50-100ms por evento
- ✅ Compatible con todos los browsers (IE10+)
- ✅ Sin límite HTTP de conexiones
- ✅ Ideal para aplicaciones real-time

**Desventajas**:
- ❌ Protocolo custom (requiere librería: `websockets` o `fastapi.WebSocket`)
- ❌ Stateful en servidor (per-conexión) → overhead de memoria
- ❌ Testing complejo (pytest-asyncio + websockets mock)
- ❌ Debugging menos observable (protocolo binario)
- ❌ Requiere soporte en proxies reversos (nginx: `proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade`)

**Performance**:
- Latencia: 50-100ms por evento
- Overhead: ~1-5ms/evento (parsing)
- Conexiones simultáneas: ~500-1000 (estateful) antes de overhead de memoria

---

## Análisis de Requisitos

### Requisitos de Negocio

| Requisito | SSE | WebSocket | Crítico? |
|---|---|---|---|
| Notificar progreso conversión | ✅ Suficiente | ✅ | SÍ |
| Actualización real-time | ⚠️ 200-500ms | ✅ 50-100ms | NO (UI puede tolerar 500ms) |
| Soportar 100+ usuarios simultáneos | ✓ Estateless | ⚠️ Stateful | MEDIA (MVP < 100) |
| Testing automatizado | ✅ Fácil | ❌ Complejo | SÍ (CI/CD) |
| Escalabilidad horizontal | ✅ | ❌ (sesiones stickiness) | MEDIA (future) |

### Requisitos Técnicos

| Requisito | SSE | WebSocket | Crítico? |
|---|---|---|---|
| Browser IE11 sin polyfill | ❌ | ✅ | NO (EOF IE11: 2022) |
| Máximo 6 conexiones/domain | ❌ Limitado | ✅ | NO (URL única) |
| Debugging observable | ✅ HTTP | ❌ Binario | MEDIA |
| Load balancer standard | ✅ | ⚠️ Sticky sessions | SÍ (infrastructure) |

---

## Decisión

**Se elige: Server-Sent Events (SSE)** para MVP, con plan de migración a WebSocket en v1.1.

### Justificación

1. **Simplicidad MVP** — Doclink es nuevo; SSE reduces time-to-market (~4h menos vs. WebSocket)
2. **Testing** — Facilita CI/CD; httpx.stream() testeable en pytest sin mock complejo
3. **Latencia tolerada** — 200-500ms es aceptable para progreso de conversión (documento tarda minutos)
4. **Escalabilidad inicial** — Suficiente para < 100 usuarios simultáneos (MVP)
5. **Observabilidad** — DevTools Network tab muestra eventos en tiempo real
6. **Compatibilidad** — FastAPI built-in, no librería extra (simplifica pyproject.toml)

### Trade-offs Aceptados

- ❌ No full-duplex (cliente no puede enviar comandos durante conversión)
  - **Mitigación**: Interface pequeña en fase 1 (solo progreso)
- ⚠️ Latencia mayor (500ms vs. 100ms)
  - **Mitigación**: UI muestra "conversión en progreso..." sin esperar cada evento
- ⚠️ No ideal para > 1000 usuarios
  - **Mitigación**: Monitorear; migrar a WebSocket + Redis en v1.1 si se alcanza

---

## Implementación

### Servidor (FastAPI)

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import asyncio
import json

app = FastAPI()

async def conversion_progress_stream(doc_ids: list[str]):
    """
    Generator que emite Server-Sent Events.
    Formato: data: {json}\n\n
    """
    for doc_id in doc_ids:
        # Simular conversión asincrónica
        start = time.time()
        result = await convert_document(doc_id)
        duration = time.time() - start
        
        event = {
            "type": "conversion_success",
            "doc_id": doc_id,
            "duration_s": duration,
            "output_path": result.markdown_path
        }
        yield f"data: {json.dumps(event)}\n\n"
        await asyncio.sleep(0.01)  # Yield control
    
    # Final event
    yield f"data: {json.dumps({'type': 'completed'})}\n\n"

@app.post("/api/convert")
async def start_conversion(doc_ids: list[str]):
    return StreamingResponse(
        conversion_progress_stream(doc_ids),
        media_type="text/event-stream"
    )
```

### Cliente (JavaScript)

```javascript
const eventSource = new EventSource("/api/convert?doc_ids=doc1,doc2,doc3");

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    switch (data.type) {
        case "conversion_success":
            updateProgress(data.doc_id, "✓");
            break;
        case "conversion_error":
            updateProgress(data.doc_id, "✗ " + data.error);
            break;
        case "completed":
            console.log("Conversión completada");
            eventSource.close();
            break;
    }
};

eventSource.onerror = () => {
    console.error("SSE error, reconectando...");
};
```

---

## Plan de Migración a WebSocket (v1.1)

Si la aplicación crece > 500 usuarios simultáneos:

1. Introducir `websockets` librería
2. Cambiar endpoint POST /api/convert → WebSocket /ws/convert
3. Permitir cliente enviar comandos: `{"cmd": "pause", "doc_id": "..."}`
4. Implementar connection pooling + Redis pub/sub para escalabilidad horizontal
5. Update client JavaScript con ws:// URL

**Esfuerzo estimado**: 8-10 horas (v1.1)

---

## Consecuencias

### Positivas
- ✅ MVP completo en menos tiempo
- ✅ Testing más rápido (no require websockets lib)
- ✅ Debugging observable en DevTools

### Negativas
- ❌ Latencia 500ms (tolerable, pero visible)
- ❌ No permite cliente enviar comandos (ejemplo: pausa conversión)
- ❌ Futuro refactor a WebSocket requerido si crece

---

## Referencias

- [RFC 6585 Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [FastAPI StreamingResponse](https://fastapi.tiangolo.com/advanced/streaming/)
- [WebSocket vs SSE (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)

---

**Revisado por**: Plan Architect  
**Aprobado por**: [Tech Lead Signature]  
**Fecha de Aprobación**: 2026-08-27
