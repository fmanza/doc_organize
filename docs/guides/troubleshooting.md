# Resolución de problemas

## `python -m doc_organize web` falla con "instala doc_organize[web]"

No tienes instalado el extra `web`. `pip install doc_organize[web]`.

## Un documento escaneado nunca sale de "OCR pendiente"

`--use-ocr` reprocesa en la misma ejecución los documentos detectados como
`ocr_required`. Si escaneaste sin `--use-ocr`, esos documentos quedan marcados
`OCR_PENDING` en el caché — vuelve a ejecutar `scan` con `--use-ocr` (no hace
falta re-escanear las carpetas de origen; el caché ya los tiene identificados).

## OCR muy lento en documentos grandes

El motor por defecto (RapidOCR) corre en CPU. Si tienes GPU disponible, instala
el extra `ocr-gpu` y añade `--use-gpu` (junto con `--use-ocr`) para usar EasyOCR
acelerado por CUDA.

## Rutas de salida muy largas o error de ruta en Windows

`DocumentConverter` replica la ruta **absoluta completa** del documento de origen
bajo `Conversión/` (no solo el nombre de archivo). Con carpetas de entrada muy
anidadas, la ruta de salida resultante puede acercarse al límite clásico de 260
caracteres de Windows. Es una limitación conocida — evita escanear jerarquías de
entrada extremadamente profundas hasta que se aborde (ver el PLAN de la Fase 1,
`§14.2`, para el análisis de una corrección propuesta).

## No puedo iniciar sesión en la web (host no-loopback)

Comprueba, en este orden:

1. ¿Existe al menos un tenant y un usuario? (`python -m doc_organize tenant create
   ...` / `user create ...`). Sin ellos, `/login` rechaza cualquier credencial.
2. ¿El `tenant_id`/usuario/contraseña son exactos? El formulario devuelve el mismo
   mensaje de error genérico tanto si el tenant no existe como si la contraseña es
   incorrecta (deliberado, evita revelar cuál de los tres campos falló).
3. ¿El navegador acepta cookies de este origen? La sesión depende de la cookie
   `doc_organize_session` (`HttpOnly`, `SameSite=Strict`).

## Cerrar sesión en una pestaña me desconecta de las demás

No debería — el logout es selectivo: solo invalida la sesión de la pestaña/
dispositivo desde la que se pide. Si observas lo contrario, es un bug; abre un
issue con los pasos para reproducirlo.

## `mkdocs build` falla por links rotos

Añadiste una página nueva a `docs/` sin registrarla en `nav:` de `mkdocs.yml` (o
al revés). `mkdocs build` valida todos los enlaces internos — corrige el `nav:`
o la ruta del fichero referenciado.
