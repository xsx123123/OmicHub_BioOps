# ADR 0001: OmicHub Memory Storage

## Status

Accepted for the memory v2 rollout.

## Decision

OmicHub uses a small, application-owned PostgreSQL layer backed by pgvector.
`memory_blocks` stores curated resident context and `memory_facts` stores
time-decayed semantic facts. Application code accesses facts through the
`FactStore` protocol so a future Qdrant or pgvectorscale migration does not
change the service contract.

Workspace memory is file-native: `MEMORY.md` is a short index and `.memory/`
contains lazily-read note bodies. Workspace files remain user-owned and are
treated as untrusted context when injected into a prompt.

## Consequences

- No hosted memory service or graph database is required.
- pgvector must be available before the v2 migrations run.
- Embeddings are currently not encrypted at rest; encryption scope requires a
  separate compliance decision because encrypted vectors cannot be filtered or
  searched by the database.
- Graphiti/graph storage is reconsidered if audit-style temporal decision
  tracing is required, and a vector backend is reconsidered above 10 million
  facts or when p99 retrieval must be below 10ms.
