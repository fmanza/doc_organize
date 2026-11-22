# Hacia 3.0: lo obsoleto

Lo que una versión 2.x marca como obsoleto sigue funcionando hasta la 3.0, pero emite `DeprecationWarning` al usarse.
Para verlo en tus tests, ejecútalos con `python -W error::DeprecationWarning -m pytest`.

## GitHub Copilot (obsoleto desde 2.1.0)

doc_organize consulta el uso y el coste de IA en el LiteLLM Proxy, que enruta todas las tareas desde la 2.0. El
consumo de GitHub Copilot Pro deja de tener sentido y se retira en 3.0:

| Obsoleto | Módulo | Qué usar |
|---|---|---|
| `GitHubCopilotUsageClient` | `doc_organize.ai` | `LiteLLMUsageClient` |
| `github_copilot_usage_config_from_env()` | `doc_organize.ai` | `litellm_usage_config_from_env()` |
| `GitHubCopilotUsageConfig` | `doc_organize.core.models` | `LiteLLMUsageConfig` |
| `UsageSourceName.GITHUB_COPILOT` | `doc_organize.core.models` | `UsageSourceName.LITELLM` (el valor de la enumeración no avisa al usarse) |

Las variables `DOC_ORGANIZE_GITHUB_USERNAME` y `DOC_ORGANIZE_GITHUB_PAT` dejan de leerse en 3.0.

```python
from doc_organize.ai import LiteLLMUsageClient, litellm_usage_config_from_env

async with LiteLLMUsageClient(litellm_usage_config_from_env()) as client:
    snapshot = await client.get_usage()
```
