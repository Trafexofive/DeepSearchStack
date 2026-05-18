# Service Port Registry

> Updated: 2026-05-18 · Session: viral-trend-analysis stack

## Port Philosophy
One proxy per stack. All internal services communicate via Docker DNS. No direct host port exposure to internal services — everything routes through stack-specific nginx reverse proxies. See [reverse-proxy.md](reverse-proxy.md) for full architecture.

## Host-Exposed Ports

| Port | Stack | Service | Route |
|---|---|---|---|
| 8080 | core | nginx | `/` → api_gateway:8000, `/inference/` → inference_gateway:8005, `/trends/` → trend-engine:8021, `/yt-lab/` → yt-lab:8020 |
| 8082 | site | nginx | Static Astro site |
| 8083 | dss | nginx | `/dss/{api,search,crawl,warehouse,vectors,agent,gateway}/` |
| 8084 | light | nginx | Same DSS routes (dev stack) |
| 8085 | test | nginx | Same DSS routes (test stack) |
| 8888 | searxng | searxng | External meta-search (not part of substrate stacks) |

## Core Stack — Internal Ports

| Service | Port | Network |
|---|---|---|
| api_gateway | 8000 | substrate-net |
| workflow_engine | 8001 | substrate-net |
| llm_gateway | 8002 | substrate-net |
| event_bus | 8003 | substrate-net |
| inference_gateway | 8005 | substrate-net, bridge-net |
| blog_generator | 8006 | substrate-net, bridge-net |
| ingest | 8008 | substrate-net, bridge-net |
| knowledge_bridge | 8010 | substrate-net, bridge-net |
| geo_audit | 8011 | substrate-net, bridge-net |
| sub_mq | 8012 | substrate-net, bridge-net |
| yt-lab | 8020 | host network |
| trend-engine | 8021 | substrate-net, bridge-net |
| proxy-rotator | 8888 | bridge-net |
| redis | 6379 | substrate-net |

## DSS Stack — Internal Ports

| Service | Port | Network |
|---|---|---|
| web-api | 8014 | deepsearch_net, bridge-net |
| deepsearch | 8001 | deepsearch_net, bridge-net |
| crawler | 8000 | deepsearch_net, bridge-net |
| knowledge-warehouse | 8009 | deepsearch_net, bridge-net |
| vector-store | 8004 | deepsearch_net |
| search-agent | 8013 | deepsearch_net, bridge-net |
| search-gateway | 8002 | deepsearch_net |
| searxng | 8080 | deepsearch_net |
| whoogle | 5000 | deepsearch_net |
| yacy | 8090 | deepsearch_net |
| postgres | 5432 | deepsearch_net |
| redis | 6379 | deepsearch_net |

## Cross-Stack Connectivity

Core and DSS share the `infra_substrate-net` bridge network. Key connections:

```
blog_generator → web-api:8014         (research via aggregate)
blog_generator → warehouse:8009       (context search)
knowledge_bridge → web-api:8014       (DSS queries from core)
inference_gateway ← web-api:8014      (LLM reconciliation)
yt-lab → inference_gateway:8005       (LLM summaries)
yt-lab → warehouse:8009               (transcript storage)
trend-engine → yt-lab:8020            (video metadata)
trend-engine → inference_gateway:8005  (LLM trend insights)
trend-engine → warehouse:8009          (content search + baseline)
crawler → proxy-rotator:8888          (outbound proxy for scraping)
```
