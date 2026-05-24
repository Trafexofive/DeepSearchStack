"""
DeepSearchStack - Common Library Setup
"""
from setuptools import setup, find_packages

setup(
    name="deepsearch-common",
    version="1.0.0",
    description="Common library for DeepSearchStack services",
    author="DeepSearchStack",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.0.0",
        "fastapi>=0.104.0",
        "httpx>=0.25.0",
    ],
    python_requires=">=3.8",
)