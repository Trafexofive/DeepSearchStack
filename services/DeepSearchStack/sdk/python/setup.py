"""
DeepSearchStack - Python SDK
Setup configuration
"""
from setuptools import setup, find_packages

# Read the contents of README file
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Read the contents of requirements file
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh.readlines() if line.strip() and not line.startswith("#")]

setup(
    name="deepsearch-sdk",
    version="0.1.0",
    author="Trafexofive",
    author_email="mlamkadm@example.com",
    description="Python SDK for DeepSearchStack services",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Trafexofive/DeepSearchStack",
    packages=find_packages(where="python"),
    package_dir={"": "python"},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-asyncio>=0.15.0",
            "pytest-cov>=2.0",
            "black>=21.0",
            "flake8>=3.0",
            "mypy>=0.800",
        ],
        "examples": [
            "jupyter>=1.0",
            "matplotlib>=3.0",
            "pandas>=1.0",
        ]
    },
    keywords=["search", "crawling", "llm", "ai", "web-scraping", "aggregation"],
    project_urls={
        "Bug Reports": "https://github.com/Trafexofive/DeepSearchStack/issues",
        "Source": "https://github.com/Trafexofive/DeepSearchStack",
        "Documentation": "https://github.com/Trafexofive/DeepSearchStack/blob/main/docs/",
    },
)