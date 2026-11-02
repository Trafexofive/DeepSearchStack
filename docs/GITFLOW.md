# Gitflow & Contribution Guide

This repository follows a streamlined, trunk-based Gitflow model with strict quality gates. `main` is always production-ready, deployable, and guaranteed to pass the end-to-end verification suite.

---

## 1. Branching Strategy

| Branch | Purpose | Rules |
|--------|---------|-------|
| `main` | Production / Stable | Protected. Every commit must pass `bash scripts/e2e_smoke.sh`. Direct commits allowed only for trivial doc typos. |
| `feature/<slug>` | New capabilities / engines | Branched from `main`. e.g., `feature/domain-presets`, `feature/deep-research-loop`. |
| `fix/<slug>` | Bug fixes / regression patches | Branched from `main`. e.g., `fix/searxng-timeout`, `fix/feed-duplicate-409`. |
| `perf/<slug>` | Latency / memory optimization | E.g., `perf/rrf-simd-ranking`, `perf/crawler-connection-pool`. |
| `chore/<slug>` | Tooling, dependencies, infra | E.g., `chore/compose-profiles`, `chore/dockerignore-volumes`. |

---

## 2. Commit Message Standard (Conventional Commits)

Format: `<type>(<scope>): <short imperative description>`

### Types
- `feat`: New feature or user/API-visible capability.
- `fix`: Bug fix or edge-case guard.
- `perf`: Performance, latency, or memory optimization.
- `refactor`: Structural rewrite without behavioral change.
- `docs`: Documentation, README, or architecture guides.
- `test`: Adding, updating, or fixing test suites.
- `chore`: Makefile updates, `.gitignore`, dependency bumps.

### Scopes
`gateway`, `crawler`, `warehouse`, `web-api`, `agent`, `ranker`, `cli`, `tui`, `infra`

### Examples
- `feat(ranker): implement RRF fusion with multi-engine consensus`
- `fix(gateway): increase provider timeout to 7s to prevent dropped scrapes`
- `chore(repo): add compiled Go binaries to gitignore`

---

## 3. The Development & Verification Lifecycle

### Step 1: Branch from Updated Main
```bash
git checkout main
git pull --rebase origin main
git checkout -b feature/my-feature
```

### Step 2: Develop with Instant Hot-Sync
Do not spend minutes rebuilding Docker images during iteration. Hot-sync modified source files into running containers:
```bash
# Example: sync search gateway changes instantly
docker cp services/search-gateway/. dss-search-gateway:/app/search_gateway/
docker restart dss-search-gateway
```

### Step 3: Run the Non-Negotiable Gate
Before merging back to `main`, the full end-to-end smoke suite **must pass**:
```bash
bash scripts/e2e_smoke.sh
```
*Zero regressions allowed.* If an endpoint or schema changes, update the test assertion and the client models in the same commit.

### Step 4: Rebase and Fast-Forward Merge
Keep git history clean, linear, and bisectable (avoid spaghetti merge bubbles):
```bash
# Update feature branch against latest main
git fetch origin
git rebase origin/main

# Fast-forward main
git checkout main
git merge --ff-only feature/my-feature
git push origin main
```

---

## 4. Repo Hygiene & Safety Rules

1. **Zero Binaries in Git:** Never commit compiled binaries (`clients/cli-go/dss`, `clients/tui-go/dss-tui`, `.o`, `.so`). They are strictly ignored by `.gitignore`.
2. **Zero Runtime Data in Git:** Never commit SQLite runtime databases, Tor state directories, or cache artifacts (`tor-data/`, `volumes/data/`).
3. **Secret Isolation:** API keys belong in `infra/env/.dev.env` or host shell environments (`~/.zshrc`). Never commit raw keys to git.
4. **Single Source of Truth:** If an internal model changes in `libs/common/models.py`, immediately propagate it to `services/` and client SDKs.
