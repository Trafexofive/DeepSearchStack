import yaml
import os
from typing import Any, Dict, Optional
from pathlib import Path


class Config:
    """Configuration manager that loads from settings.yml and environment variables"""
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "settings.yml"
        
        self.config_path = config_path
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value with dot notation support.
        Environment variables override config file values.
        
        Example:
            config.get("search.max_results")
            ENV: DEEPSEARCH_SEARCH_MAX_RESULTS=200
        """
        # Check environment variable first
        env_key = "DEEPSEARCH_" + key_path.upper().replace(".", "_")
        env_value = os.environ.get(env_key)
        
        if env_value is not None:
            # Try to convert to appropriate type
            return self._convert_type(env_value)
        
        # Navigate through nested config
        keys = key_path.split(".")
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def _convert_type(self, value: str) -> Any:
        """Convert string environment variable to appropriate type"""
        # Boolean
        if value.lower() in ('true', 'yes', '1', 'on'):
            return True
        if value.lower() in ('false', 'no', '0', 'off'):
            return False
        
        # Number
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        # List (comma-separated)
        if ',' in value:
            return [v.strip() for v in value.split(',')]
        
        # String
        return value
    
    def get_service_url(self, service: str) -> str:
        """Get service URL with environment variable override"""
        env_key = f"{service.upper()}_URL"
        return os.environ.get(env_key, self.get(f"services.{service}"))
    
    @property
    def search_config(self):
        """Get search configuration section"""
        return self.get("search", {})
    
    @property
    def scraping_config(self):
        """Get scraping configuration section"""
        return self.get("scraping", {})
    
    @property
    def rag_config(self):
        """Get RAG configuration section"""
        return self.get("rag", {})
    
    @property
    def synthesis_config(self):
        """Get synthesis configuration section"""
        return self.get("synthesis", {})
    
    @property
    def cache_config(self):
        """Get cache configuration section"""
        return self.get("cache", {})
    
    @property
    def session_config(self):
        """Get session configuration section"""
        return self.get("sessions", {})


# Global config instance
config = Config()
