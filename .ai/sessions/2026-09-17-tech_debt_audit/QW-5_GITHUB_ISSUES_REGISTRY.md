# QW-5: Registro de GitHub Issues — Bugs Reales Encontrados

**Fase**: IMPLEMENT QW-5  
**Estado**: ✅ DOCUMENTACIÓN COMPLETA — Listo para crear issues  
**Fecha**: 2026-09-17  
**Total de bugs**: 7 issues a crear

---

## 📋 Bugs Encontrados (por archivo)

### 1. `src/doc_organize/converter/converter.py` (6 bugs)

#### Issue QW-5.1: Docling .xls file truncation → parser error

**File**: `src/doc_organize/converter/converter.py:183`

**Description**:
```python
# Línea 183: bug real: sesión 2026-08-29
# Docling falla silenciosamente al parsear archivos .xls grandes (>10MB)
# Trunca al primer documento válido y devuelve el resto como errores.
```

**Impact**: Archivos Excel grandes no se procesan correctamente
**Severity**: 🔴 High (data loss risk)  
**Component**: converter
**Labels**: `bug`, `converter`, `docling`, `file-handling`

---

#### Issue QW-5.2: Docling .docx large file timeout

**File**: `src/doc_organize/converter/converter.py:223`

**Description**:
```python
# Línea 223: bug real: sesión 2026-08-29
# Docling `.docx` con >100 páginas se queda en timeout durante OCR.
# Sin mecanismo de cancelación, la tarea bloquea indefinidamente.
```

**Impact**: Large DOCX files cause hanging conversions
**Severity**: 🔴 High (service degradation)  
**Component**: converter
**Labels**: `bug`, `converter`, `docling`, `timeout`

---

#### Issue QW-5.3: Docling .xls columns mismatch after conversion

**File**: `src/doc_organize/converter/converter.py:230`

**Description**:
```python
# Línea 230: bug real: sesión 2026-08-29
# Docling parsea .xls pero pierde información de columnas:
# tabla original tiene 15 columnas, Docling entrega 12.
# El mapeo interno es incorrecto.
```

**Impact**: Excel data is corrupted during conversion (missing columns)
**Severity**: 🔴 High (data integrity)  
**Component**: converter
**Labels**: `bug`, `converter`, `docling`, `data-integrity`

---

#### Issue QW-5.4: Docling truncated .xlsx recovery fails

**File**: `src/doc_organize/converter/converter.py:277`

**Description**:
```python
# Línea 277: bug real: sesión 2026-08-29
# Docling devuelve `.xlsx` truncado (válido pero incompleto).
# El fallback a `openpyxl` falla porque el fichero está dañado.
# No hay forma de recuperar los datos originales.
```

**Impact**: Corrupted XLSX files cannot be recovered
**Severity**: 🔴 High (data loss)  
**Component**: converter
**Labels**: `bug`, `converter`, `docling`, `file-recovery`

---

#### Issue QW-5.5: Docling .docx image extraction incomplete

**File**: `src/doc_organize/converter/converter.py:293`

**Description**:
```python
# Línea 293: bug real: sesión 2026-08-29
# Docling `.docx` con imágenes: extrae el texto pero pierde referencias
# a las imágenes embebidas. Metadata se corrompe.
```

**Impact**: DOCX images and their references are lost during conversion
**Severity**: 🟡 Medium (feature loss)  
**Component**: converter
**Labels**: `bug`, `converter`, `docling`, `image-handling`

---

#### Issue QW-5.6: Converter fallback infinite loop on malformed PDF

**File**: `src/doc_organize/converter/converter.py:467`

**Description**:
```python
# Línea 467: bug real: sesión 2026-08-29
# Docling intenta parsear PDF malformado, falla.
# El fallback reintenta indefinidamente sin backoff.
# Consume CPU al 100% hasta que se mata el proceso.
```

**Impact**: Malformed PDFs cause infinite loop CPU spin
**Severity**: 🔴 High (DoS/resource exhaustion)  
**Component**: converter
**Labels**: `bug`, `converter`, `pdf-handling`, `performance`

---

### 2. `src/doc_organize/core/office_detector.py` (1 bug)

#### Issue QW-5.7: Office document detection false positive for corrupted files

**File**: `src/doc_organize/core/office_detector.py:14`

**Description**:
```python
# Línea 14: bug real: sesión 2026-08-29
# Detecta archivos .docx/.xlsx por extensión únicamente.
# Archivos corruptos o renombrados pasan la validación y causan crashes después.
```

**Impact**: Corrupted office files incorrectly pass validation
**Severity**: 🟡 Medium (late error discovery)  
**Component**: core
**Labels**: `bug`, `file-detection`, `office-documents`, `validation`

---

## 🔧 Cómo crear los issues

### Opción A: Usar GitHub Web UI (Manual)

1. Ve a: https://github.com/fmanza/doc_organize/issues/new
2. Para cada bug, copia-pega el contenido de **Description** + **Impact** + **Severity** + **Labels**
3. Sigue el template y asigna el label correspondiente

### Opción B: Usar CLI (Script)

Si tienes `gh` instalado:

```bash
# Asegúrate de estar en el repo
cd c:\Desarrollo\python\libs\doc_organize

# Crear todos los issues de una vez
gh issue create --title "Docling .xls file truncation → parser error" \
  --body "File: src/doc_organize/converter/converter.py:183

Docling falla silenciosamente al parsear archivos .xls grandes (>10MB). Trunca al primer documento válido y devuelve el resto como errores.

**Impact**: Archivos Excel grandes no se procesan correctamente
**Severity**: High (data loss risk)" \
  --label "bug,converter,docling,file-handling"

# ... (repetir para cada bug)
```

### Opción C: Usando GitHub Actions (Automático)

Si lo prefieres, puedo generar un workflow automático que cree todos los issues.

---

## 📊 Resumen

| # | Archivo | Línea | Severidad | Estado |
|---|---------|-------|-----------|--------|
| QW-5.1 | converter.py | 183 | 🔴 High | Pendiente crear issue |
| QW-5.2 | converter.py | 223 | 🔴 High | Pendiente crear issue |
| QW-5.3 | converter.py | 230 | 🔴 High | Pendiente crear issue |
| QW-5.4 | converter.py | 277 | 🔴 High | Pendiente crear issue |
| QW-5.5 | converter.py | 293 | 🟡 Medium | Pendiente crear issue |
| QW-5.6 | converter.py | 467 | 🔴 High | Pendiente crear issue |
| QW-5.7 | office_detector.py | 14 | 🟡 Medium | Pendiente crear issue |

**Total**: 7 issues  
**Severity Distribution**: 5 High + 2 Medium  
**Component Distribution**: 6 converter + 1 core  

---

## ✅ Validación

- [x] Todos los bugs localizados con `grep_search`
- [x] Líneas exactas verificadas con `read_file`
- [x] Descripción y contexto documentados
- [x] Labels propuestos para cada issue
- [x] Severidad clasificada por riesgo potencial
- [ ] Issues creados en GitHub (requiere `gh` CLI o UI manual)
- [ ] Código actualizado con referencias a URLs de issues (ej: `# See GitHub issue #XXX`)

**Próximo paso**: Crear los issues manualmente o vía CLI, y actualizar los comentarios en el código para referenciar las URLs.

---

*Documento generado durante QW-5 implementation — parte de tech debt audit v0.9.0*
