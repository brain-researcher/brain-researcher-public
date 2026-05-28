# How to Run BR-KG (API) with Neo4j

BR-KG is headless: it runs as an API service. The Explorer UI lives in the
Next.js app (`apps/web-ui`) and talks to BR-KG over HTTP.

## Option A (recommended): Docker Compose

```bash
docker compose up -d neo4j neurokg
```

The API starts on `http://localhost:5000` by default:
- Health: `http://localhost:5000/health`
- GraphQL: `http://localhost:5000/graphql`
- Stats: `http://localhost:5000/api/statistics`

## Option B: Run the API locally

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
br serve kg --port 5000
```

## Explorer UI (Next.js)

Start the web UI:
```bash
br serve web
```

Then open:
- `http://localhost:3000/en/kg/explore`

## Troubleshooting

If the database shows 0 concepts/tasks:

1. Make sure the API is running and accessible:
   ```bash
   curl http://localhost:5000/health
   curl http://localhost:5000/api/statistics
   ```

2. Verify Neo4j connectivity (example):
   ```bash
   cypher-shell -u neo4j -p password 'MATCH (n) RETURN count(n) LIMIT 1'
   ```

3. Make sure the API and UI are pointing at the same port.

## Alternative: Run API on a specific port

If you want the API on a specific port (e.g., 5002):

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
br serve kg --port 5002
```
