

# DeepSearchStack: Your Private, Self-Hosted AI Search and Reasoning Engine

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)![Version: 1.0.0](https://img.shields.io/badge/Version-1.0.0-green.svg)![Python Version](https://img.shields.io/badge/Python-3.11+-blue?logo=python)![Docker Support](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)

DeepSearchStack is a comprehensive, privacy-first, and fully self-hostable search and intelligence platform. It moves beyond simple keyword matching by integrating multiple search backends with a powerful, multi-provider LLM gateway. This allows it to perform federated searches, understand context, and synthesize high-quality, cited answers to complex questions—all while running on your own hardware.

Regain sovereignty over your data and build your own private search and reasoning engine.

## ✨ Core Features

-   🧠 **AI-Synthesized Answers:** Instead of just a list of links, get direct, comprehensive answers to your questions, synthesized from multiple sources by a Large Language Model.
-   🔒 **Privacy-First & Self-Hosted:** The entire stack runs on your own infrastructure. Your queries and data never leave your control. No tracking, no ads.
-   🌐 **Federated Search:** Gathers results from multiple backends simultaneously (including privacy-respecting meta-search engines and peer-to-peer networks) for comprehensive coverage.
-   🔌 **Multi-Provider LLM Gateway:** A resilient, non-blocking gateway that supports local models via **Ollama** and can be extended with external APIs like **Groq** and **Gemini**. It's designed for high availability with automatic provider fallback.
-   📚 **Retrieval-Augmented Generation (RAG) Ready:** The architecture is built to support a true RAG pipeline, with a dedicated vector store for semantic retrieval.
-   🚀 **Simple Deployment:** The entire stack is containerized with Docker and managed with a powerful `Makefile`, allowing you to go from clone to query in minutes.
-   🖥️ **Web Interface:** Includes OpenWebUI for a user-friendly chat interface to interact with your LLMs.
-   🔧 **Extensible & Configurable:** Easily enable or disable LLM providers, configure which models to use, and add new search backends.

##  Showcase: Live Demo Output

DeepSearchStack doesn't just return links. It understands, synthesizes, and cites its sources.

**Query:** `python3 examples/query_search_agent.py`

```
Response from Search Agent:
Answer: The latest news on Gemini projects depends on which "Gemini" project you're referring to.  There are several:

**Google's Gemini AI models:**  The most recent updates concern Gemini 1.5 Pro and Gemini 1.5 Flash, which are now generally available [4].  A cost-efficient and faster version, Gemini 1.5 Flash-Lite, has also been released [4].  These models show improvements in coding, science, reasoning, and multimodal benchmarks [2], and now include native audio output for a more natural conversational experience and advanced security safeguards [10].  Further development includes Project Mariner, a research tool enabling human-agent interaction, coming to the Gemini API and Vertex AI [9].

**NASA's Gemini Project:** This refers to the crewed spaceflights of the 1960s.  The final mission, Gemini 12, concluded the program [1]. There are also references to later updates, with mentions of Gemini II in May 2025 [7], but these lack specific details.

**Other Gemini Projects:** A project called GEMINI, hosted by TU Dublin, was formally launched in November 2024 [5].

Sources:
- Project Gemini - NASA: https://www.nasa.gov/gemini/
- Get the latest news about Google Gemini: https://gemini.google/latest-news/
- Official Gemini news and updates | Google Blog: https://blog.google/products/gemini/
- News and Events | GEMINI - Demonstration to Transformation: https://geminigeothermal.com/news/
- Google introduces Gemini 1.0: A new AI model for the agentic era: https://blog.google/technology/google-deepmind/google-gemini-ai-update-december-2024/
- ...and many more.
```

## 🏗️ Architecture

The stack is composed of several microservices that work in concert, providing a clear separation of concerns and enabling scalability.

```mermaid
graph TD
    subgraph User_Interaction
        CLI[CLI / API Client]
        WebApp[Web UI (web-api)]
        OpenWebUI[OpenWebUI]
    end

    subgraph Core_Logic
        SearchAgent[Search Agent (search-agent)]
        LLMGateway[LLM API Gateway (llm-gateway)]
    end

    subgraph AI_Data_Services
        Ollama[Ollama (Local LLM)]
        VectorStore[Vector Store (ChromaDB)]
        Postgres[PostgreSQL (Metadata)]
    end

    subgraph External_APIs
        GroqAPI[Groq Cloud API]
        GeminiAPI[Google Gemini API]
    end
    
    subgraph Search_Backends
        Whoogle[Whoogle]
        SearXNG[SearXNG]
        YaCy[YaCy (P2P)]
    end

    CLI --> SearchAgent
    WebApp --> SearchAgent
    OpenWebUI --> LLMGateway
    SearchAgent --> Whoogle
    SearchAgent --> SearXNG
    SearchAgent --> YaCy
    SearchAgent --> LLMGateway
    LLMGateway --> Ollama
    LLMGateway --> GroqAPI
    LLMGateway --> GeminiAPI
    SearchAgent --> VectorStore
    SearchAgent --> Postgres
```
---

## 🚀 Getting Started (Quick Start)

Get the entire stack up and running in just a few commands.

**Prerequisites:**
*   Git
*   Docker & Docker Compose

**1. Clone the Repository**```bash
git clone https://github.com/your-username/DeepSearchStack.git
cd DeepSearchStack
```

**2. Configure Your Environment**
Copy the example environment file. By default, the stack will run with only the local Ollama provider.

```bash
cp .env.example .env
```

*Optional:* To enable external providers, edit the `.env` file and add your API keys:
```env
# In your .env file
ENABLE_GEMINI=true
ENABLE_GROQ=true
GEMINI_API_KEY="your_gemini_api_key_here"
GROQ_API_KEY="your_groq_api_key_here"
```

**3. Run the Stack**
This command will build the Docker images and start all services in the correct order. The first time you run this, Ollama will download the default models, which may take several minutes.

```bash
make up
```

**4. Query the Agent!**
Once all services are healthy, you can query the `search-agent`:
```bash
python3 examples/query_search_agent.py
```

**5. Access the Web Interface**
Open your browser and navigate to `http://localhost:3000` to access the OpenWebUI interface for chatting with your LLMs.

---

## ⚙️ Configuration

All configuration is managed through the `.env` file.

| Variable                 | Description                                                                 | Default      |
| ------------------------ | --------------------------------------------------------------------------- | ------------ |
| `ENABLE_GEMINI`          | Set to `true` to enable the Google Gemini provider.                         | `false`      |
| `ENABLE_GROQ`            | Set to `true` to enable the Groq Cloud provider.                            | `false`      |
| `GEMINI_API_KEY`         | Your API key for Google Gemini.                                             | `""`         |
| `GROQ_API_KEY`           | Your API key for Groq Cloud.                                                | `""`         |
| `OLLAMA_MODELS_PULL`     | Comma-separated list of models for the Ollama service to pull on startup.   | `gemma:2b,codellama`  |
| `OLLAMA_DEFAULT_MODEL`   | The model the `llm-gateway` will request from Ollama. **Must be in `OLLAMA_MODELS`**. | `gemma3:1b`  |
| `POSTGRES_DB`            | The name of the PostgreSQL database.                                        | `searchdb`   |
| `POSTGRES_USER`          | The username for the PostgreSQL database.                                   | `searchuser` |
| `POSTGRES_PASSWORD`      | The password for the PostgreSQL database.                                   | `searchpass` |
| `OPENWEBUI_PORT`         | The port on which OpenWebUI will be accessible.                             | `3000`       |

## 🛠️ Usage & Management

The `Makefile` is your primary tool for managing the stack.

| Command             | Description                                                              |
| ------------------- | ------------------------------------------------------------------------ |
| `make up`           | Start all services in detached mode.                                     |
| `make down`         | Stop and remove all services and networks.                               |
| `make logs`         | Follow the logs of all running services.                                 |
| `make logs service=<name>` | Follow the logs of a specific service (e.g., `llm-gateway-1`). |
| `make re`           | Rebuild all Docker images and restart the stack.                         |
| `make stop`         | Stop all services without removing them.                                 |
| `make test`         | Run the integration test suite against the running stack.                |
| `make ssh service=<name>`  | Get an interactive shell inside a running service container.      |
| `make prune`        | A deep clean that stops the stack and removes all volumes and images.    |

### API Examples

You can interact with the services directly via `curl`.

**Check LLM Gateway Health & Providers:**
```bash
curl http://localhost:8080/health
curl http://localhost:8080/providers
```

**Send a Completion Request to a Specific Provider:**
```bash
curl -X POST http://localhost:8080/completion \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "groq",
    "messages": [{"role": "user", "content": "What is the capital of Spain?"}]
  }'
```

**Perform an End-to-End Search:**
```bash
curl -X POST http://localhost:8001/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the core principles of responsive web design?"}'
```

**Access OpenWebUI:**
Open your browser and navigate to `http://localhost:3000` to access the web interface.

---

## 🔬 Development Guide

Interested in contributing? Here's how to get started.

**Project Structure:**
```
.
├── docker-compose.yml       # Main Docker Compose file
├── .env.example             # Environment variable template
├── Makefile                 # Management commands
├── llm_gateway/             # The resilient, multi-provider LLM gateway
├── search-agent/            # Core agent logic for search and synthesis
├── vector-store/            # RAG-enabling vector database service
├── crawler/                 # Web crawling service with crawl4ai
├── openwebui/               # Web interface for chatting with LLMs
├── testing/                 # Pytest integration tests
├── examples/                # Example client scripts
└── ... (other service directories)
```

**Running Tests:**
Ensure the stack is running, then execute the test script:
```bash
# This script loads the .env file and runs a full suite of tests.
./test.sh
```

## 💻 Technology Stack

| Component         | Technology                               |
| ----------------- | ---------------------------------------- |
| **Orchestration** | Docker, Docker Compose                   |
| **Backend API**   | Python, FastAPI, Uvicorn                 |
| **LLM Gateway**   | httpx (async requests), Pydantic         |
| **Local LLM**     | Ollama                                   |
| **Vector Store**  | ChromaDB, Sentence-Transformers          |
| **Metadata Store**| PostgreSQL                               |
| **Search Engines**| Whoogle, SearXNG, YaCy                   |
| **Web Crawling**  | crawl4ai, Playwright                     |
| **Testing**       | Pytest, pytest-httpx                     |

## 🗺️ Roadmap

We have an ambitious vision for this project. Our high-level goals are outlined in our **[ROADMAP.md](ROADMAP.md)** file, which includes plans for a full RAG pipeline, conversational memory, multi-modal search, and a rich web UI.

## 🤝 Contributing

Contributions are welcome! Whether it's improving documentation, adding a new search provider, or implementing a new feature from the roadmap, we'd love your help. Please read our (forthcoming) `CONTRIBUTING.md` for guidelines.

## 📄 License

This project is licensed under the MIT License. See the **[LICENSE](LICENSE)** file for details.
