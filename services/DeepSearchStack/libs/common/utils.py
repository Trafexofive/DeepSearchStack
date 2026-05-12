"""
DeepSearchStack - Common Utilities Module
Shared utilities across services
"""
import os
import logging
from typing import Optional, Dict, Any
from urllib.parse import urljoin


class ConfigManager:
    """Centralized configuration manager for services"""
    
    @staticmethod
    def get_service_url(service_name: str, default_port: Optional[str] = None) -> str:
        """
        Get service URL from environment variables with fallbacks
        Format: {SERVICE_NAME_UPPER}_URL or http://service-name:default_port
        """
        env_var = f"{service_name.upper()}_URL"
        url = os.getenv(env_var)
        
        if url:
            return url
        
        # Fallback to default service URL
        if default_port:
            return f"http://{service_name.replace('_', '-')}: {default_port}"
        else:
            # Default port mappings
            port_map = {
                "search_gateway": "8002",
                "llm_gateway": "8080",
                "vector_store": "8004",
                "crawler": "8000",
                "redis": "6379",
                "postgres": "5432"
            }
            default_port = port_map.get(service_name, "8000")
            return f"http://{service_name.replace('_', '-')}: {default_port}"
    
    @staticmethod
    def get_env_var(var_name: str, default_value: Optional[str] = None) -> str:
        """Get environment variable with default fallback"""
        return os.getenv(var_name, default_value)


class LoggerSetup:
    """Common logging configuration"""
    
    @staticmethod
    def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
        """Set up a logger with common configuration"""
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level.upper()))
        
        # Avoid adding multiple handlers
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger


class ServiceClient:
    """Base service client with common functionality"""
    
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout
    
    def build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint"""
        if endpoint.startswith(('http://', 'https://')):
            return endpoint
        return urljoin(self.base_url, endpoint)