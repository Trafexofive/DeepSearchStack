"""
DeepSearchStack - Common Configuration Module
Centralized configuration and service discovery
"""
import os
from typing import Optional, Dict, Any
from urllib.parse import urljoin
from libs.common.utils import ConfigManager

# Service configuration with default URLs
SERVICE_CONFIG = {
    "search_gateway": {
        "default_url": "http://search-gateway:8002",
        "env_var": "SEARCH_GATEWAY_URL",
        "health_endpoint": "/health"
    },
    "llm_gateway": {
        "default_url": "http://llm-gateway:8080",
        "env_var": "LLM_GATEWAY_URL", 
        "health_endpoint": "/health"
    },
    "vector_store": {
        "default_url": "http://vector-store:8004",
        "env_var": "VECTOR_STORE_URL",
        "health_endpoint": "/health"
    },
    "crawler": {
        "default_url": "http://crawler:8000",
        "env_var": "CRAWLER_URL",
        "health_endpoint": "/health"
    },
    "redis": {
        "default_url": "redis://redis:6379/0",
        "env_var": "REDIS_URL",
    },
    "postgres": {
        "default_url": "postgresql://searchuser:searchpass@postgres:5432/searchdb",
        "env_var": "POSTGRES_URL",
    }
}


class ServiceDiscovery:
    """Handles service discovery and configuration"""
    
    @staticmethod
    def get_service_url(service_name: str) -> str:
        """Get service URL with proper fallbacks"""
        if service_name in SERVICE_CONFIG:
            config = SERVICE_CONFIG[service_name]
            env_var = config["env_var"]
            default_url = config["default_url"]
            
            return os.getenv(env_var, default_url)
        else:
            # Fallback for services not in the predefined config
            return ConfigManager.get_service_url(service_name)
    
    @staticmethod
    def get_all_service_urls() -> Dict[str, str]:
        """Get all service URLs as a dictionary"""
        return {
            name: ServiceDiscovery.get_service_url(name) 
            for name in SERVICE_CONFIG.keys()
        }


class Config:
    """Centralized configuration access"""
    
    def __init__(self):
        self.services = ServiceDiscovery()
    
    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """Get configuration value by key"""
        return os.getenv(key, default)
    
    def get_service_url(self, service_name: str) -> str:
        """Get service URL"""
        return self.services.get_service_url(service_name)
    
    def get_timeout(self, service_name: str, default: float = 30.0) -> float:
        """Get timeout for a specific service"""
        timeout_env = f"{service_name.upper()}_TIMEOUT"
        timeout_str = os.getenv(timeout_env)
        
        if timeout_str:
            try:
                return float(timeout_str)
            except ValueError:
                pass
        return default


# Global config instance
config = Config()