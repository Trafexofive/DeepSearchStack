# DeepSearchStack Common Library

The Common Library is a shared collection of components designed to reduce coupling between microservices in the DeepSearchStack architecture. It provides standardized models, utilities, and configuration management that can be reused across services.

## Components

### Models (`libs.common.models`)
- **Shared Pydantic models**: Standardized data structures for requests, responses, and entities
- **Search-related models**: `SearchResult`, `SearchGatewayRequest`, `SearchProvider`, etc.
- **LLM-related models**: `Message`, `SynthesizeRequest`, `StreamingChunk`, etc.
- **RAG and content models**: `ScrapedContent`, `VectorChunk`, etc.
- **DeepSearch models**: `DeepSearchRequest`, `DeepSearchResponse`, etc.

### Utilities (`libs.common.utils`)
- **ConfigManager**: Centralized configuration management with environment variable fallbacks
- **LoggerSetup**: Standardized logging configuration across services
- **ServiceClient**: Base service client with common functionality

### Configuration (`libs.common.config`)
- **ServiceDiscovery**: Centralized service URL management and discovery
- **Config**: Standard configuration access with fallback mechanisms

## Benefits

1. **Reduced Duplication**: Eliminates duplicated model definitions across services
2. **Consistent Interfaces**: Ensures consistent data structures across the stack
3. **Improved Maintainability**: Changes to common models only need to be made in one place
4. **Better Decoupling**: Services can evolve independently while maintaining compatibility
5. **Easier Testing**: Common components can be tested in isolation

## Usage

To use common models in your service:

```python
from libs.common.models import SearchResult, SearchGatewayRequest
from libs.common.config import config
from libs.common.utils import LoggerSetup

# Get service URLs through common configuration
search_gateway_url = config.get_service_url("search-gateway")
```

## Migration Path

The library maintains backward compatibility by re-exporting models from existing service-specific modules. Services should gradually migrate to import directly from `libs.common.models` instead of local model files.