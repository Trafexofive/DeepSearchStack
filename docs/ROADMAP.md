
# DeepSearchStack Project Roadmap

This document outlines the strategic development plan for DeepSearchStack. Our mission is to build a powerful, privacy-first, and fully self-hostable AI reasoning and search engine that empowers users with control over their data and intelligence tools.

The roadmap is divided into three phases:
1.  **Phase 1: Bedrock (Current - Q3 2025)** - Focus on core stability, performance, and foundational AI capabilities.
2.  **Phase 2: Augmentation (Q4 2025 - Q1 2026)** - Focus on expanding knowledge sources, user interaction, and multi-modal understanding.
3.  **Phase 3: Autonomy (Q2 2026 and beyond)** - Focus on proactive intelligence, multi-agent systems, and self-improvement.

---

## Phase 1: Bedrock (Current - Q3 2025)
**Goal:** Solidify the core architecture, making the system fast, reliable, and more intelligent in its core search-and-synthesis loop.

### 🚀 Core Features & AI
-   **`[In Progress]` Caching Layer:** Implement a Redis-based cache in the `llm-gateway` to dramatically improve response times for repeated queries.
-   **`[In Progress]` Retrieval-Augmented Generation (RAG):** Transition the `search-agent` from basic context stuffing to a true RAG pipeline. This involves using the vector store to semantically rank and retrieve the most relevant information chunks before sending them to the LLM for synthesis.
-   **Knowledge Graph Integration (Proof of Concept):** Begin integrating a local graph database (e.g., Neo4j) to store and query relationships between entities found in search results. The `search-agent` will perform simple entity extraction and store "subject-predicate-object" triplets.
-   **Advanced Query Understanding:** Implement a query pre-processing step in the `search-agent` to identify user intent (e.g., "summarize," "compare," "explain") and entities. This will allow for more targeted search strategies.

### 🏗️ Infrastructure & Performance
-   **`[In Progress]` CI/CD Pipeline:** Establish a robust CI pipeline using GitHub Actions to automate linting, testing, and Docker image builds.
-   **Observability Stack:** Add Prometheus for metrics collection and Grafana for dashboarding. Key metrics will include API latency, provider success/failure rates, and resource usage.
-   **Configuration Management:** Refactor all hardcoded settings (model names, prompts, URLs) into a centralized, environment-aware configuration system (e.g., using Pydantic's `BaseSettings`).

### 🧪 Testing & Quality
-   **Comprehensive Test Suite:** Achieve >80% test coverage for the Python-based services, with a focus on testing failure modes, API contracts, and integration points.
-   **Benchmarking Framework:** Create a `benchmarking` suite to measure end-to-end performance (query latency, RAG accuracy) and track regressions.

---

## Phase 2: Augmentation (Q4 2025 - Q1 2026)
**Goal:** Enhance the system's ability to ingest and understand diverse information sources and improve the user's ability to interact with it.

### 🚀 Core Features & AI
-   **Multi-Modal RAG:** Extend the vector store and RAG pipeline to handle images and potentially short audio clips. Users will be able to ask questions about the content of images found in search results.
-   **Personal Knowledge Base Integration:** Develop connectors to allow the `crawler` service to index local document folders (PDFs, Markdown) and popular note-taking apps (Obsidian, Logseq). This will enable the agent to answer questions based on the user's personal knowledge.
-   **Conversational Memory:** Give the `search-agent` a persistent memory (stored in Redis or Postgres). This will allow for follow-up questions and context-aware conversations, transforming it from a simple Q&A tool into a true research assistant.
-   **Hybrid Search:** Enhance the RAG pipeline to use a hybrid of semantic (vector) search and traditional keyword (full-text) search, leveraging the strengths of both for more accurate retrieval.

### 🖥️ User Interface & Experience
-   **Interactive Web UI:** Evolve the `web-api` into a rich frontend application (e.g., using SvelteKit or Next.js) that supports conversational chat, displays sources alongside answers, and allows for feedback on response quality.
-   **API for Developers:** Formalize the `web-api` into a stable, versioned REST API with OpenAPI documentation, allowing third-party applications to leverage the DeepSearchStack's capabilities.

### 🏗️ Infrastructure & Performance
-   **Distributed Crawling:** Refactor the `crawler` to support multiple worker instances, enabling faster and more scalable ingestion of data.
-   **Optimized Embedding Models:** Research and integrate more efficient and powerful embedding models (e.g., models fine-tuned for retrieval tasks).

---

## Phase 3: Autonomy (Q2 2026 and Beyond)
**Goal:** Evolve the system from a reactive search tool into a proactive, autonomous intelligence agent.

### 🚀 Core Features & AI
-   **Autonomous Agent Framework:** Implement a true agentic framework (e.g., based on ReAct or similar principles) where the LLM can decide which tools to use (web search, knowledge graph query, personal document search) and chain them together to answer complex, multi-hop questions.
-   **Proactive Monitoring & Summarization:** Allow users to define topics of interest. The system will autonomously monitor new information, and the agent will provide periodic summaries and alerts.
-   **Self-Improvement through Feedback:** Use the feedback collected from the Web UI to create datasets for fine-tuning the LLMs and retrieval models, allowing the system to improve its accuracy and helpfulness over time.
-   **Multi-Agent Systems:** Introduce the concept of specialized agents (e.g., a "Code Analysis Agent," a "Financial Research Agent") that can collaborate to solve complex user requests.

### 🌐 Ecosystem & Community
-   **Plugin Architecture:** Develop a plugin system that allows the community to easily add new data sources, tools, and even custom agent behaviors.
-   **Model Fine-Tuning Hub:** Create a framework and share scripts to help users fine-tune open-source LLMs on their own data, fostering a community of specialized models.
-   **Federated Knowledge Sharing:** Explore privacy-preserving methods (e.g., federated learning) for users to optionally share insights from their knowledge graphs without exposing the underlying data, creating a distributed, collaborative intelligence network.
