# Architecture governance

This directory is the working record for the ongoing architectural-entropy
reduction programme. It is excluded from the generated documentation site
(`.barnacle.json`) because it records the _process_, not the product.

```mermaid
flowchart LR
    scan("<img src='barnacle:search.svg' width='20' alt=''/><br/>Scan entropy") --> pool("<img src='barnacle:list.svg' width='20' alt=''/><br/><u>TASK_POOL.md<br/>ranked work</u>")
    pool --> adr("<img src='barnacle:file-text.svg' width='20' alt=''/><br/><u>ADR-*.md<br/>decisions</u>")
    adr --> batch("<img src='barnacle:pen-line.svg' width='20' alt=''/><br/>Refactor batch")
    batch --> verify("<img src='barnacle:check.svg' width='20' alt=''/><br/><u>PROGRESS.md<br/>baseline + verification</u>")
    verify --> scan
    click pool href "TASK_POOL.md"
    click verify href "PROGRESS.md"
    class pool,verify mdFile
    classDef mdFile fill:#dcd6ce,stroke:#6b6255,color:#292524
```

- [PROGRESS.md](PROGRESS.md) — baseline, completed batches, verification evidence.
- [TASK_POOL.md](TASK_POOL.md) — ranked candidate work, with status.
- [ADR-0001](ADR-0001-architecture-governance.md) — why this record exists and how batches are structured.
