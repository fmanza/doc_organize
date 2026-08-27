# Politica de seguridad

## Reporte responsable

Si detectas una vulnerabilidad o una exposicion de datos, no abras una issue publica con detalles explotables.

Usa un canal privado con el mantenedor del repositorio y comparte:

- descripcion del problema
- impacto estimado
- pasos de reproduccion minimos
- versiones afectadas
- propuesta de mitigacion si la tienes

## Alcance prioritario

- inyeccion SQL o construccion insegura de queries
- manejo de credenciales y secretos
- fugas de informacion en logs, errores o artefactos generados
- validacion insuficiente de entradas
- cierre incorrecto de recursos sync/async

## Buenas practicas del proyecto

- no incluir credenciales reales en ejemplos o tests
- usar parametrizacion o escape seguro de identificadores cuando aplique
- documentar limitaciones de introspeccion por motor en lugar de inventar metadatos
