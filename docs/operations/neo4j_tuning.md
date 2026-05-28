# Neo4j Tuning Cheatsheet

Run the helper script with sudo to raise heap/page cache and remove transaction timeouts:

```bash
sudo scripts/ops/tune_neo4j_memory.sh
```

Optional overrides:

```bash
sudo NEO4J_HEAP_SIZE=10g NEO4J_PAGECACHE_SIZE=8g scripts/ops/tune_neo4j_memory.sh
```

This script:

1. Backs up `/etc/neo4j/neo4j.conf`.
2. Sets `server.memory.heap.initial_size` and `server.memory.heap.max_size` to the specified heap.
3. Sets `server.memory.pagecache.size`.
4. Sets `dbms.transaction.timeout` (default 0 = unlimited).
5. Restarts `neo4j.service` and prints the status.

> Note: You need sudo rights because `/etc/neo4j/neo4j.conf` is owned by `neo4j:adm`.
