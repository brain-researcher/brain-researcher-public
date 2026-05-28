# BR-KG Smart Search Guide

## Overview

The BR-KG smart search feature allows you to search the knowledge graph using natural language queries. The system automatically understands your intent, extracts relevant filters, and generates the appropriate database query.

## Key Features

### 1. Natural Language Understanding
- Type queries in plain English
- No need to learn complex query syntax
- System automatically detects entity types and filters

### 2. Transparent Query Processing
- See exactly how your query was interpreted
- View extracted concepts, brain regions, tasks, and date ranges
- Inspect the generated Cypher query for learning

### 3. Smart Actions
- **Summarize**: Get AI-generated summaries of selected nodes
- **Find Similar**: Discover related entities based on graph structure
- **Export**: Download results in various formats

## API Endpoints

### Smart Search
```
POST/GET /api/search/smart
```
- Parameters:
  - `query`: Natural language search query
  - `limit`: Maximum results (default: 100)

### Summarize Selection
```
POST /api/summarize
```
- Body:
  - `node_ids`: Array of node IDs to summarize
  - `max_length`: Maximum summary length

### Find Similar Nodes
```
GET /api/similar/<node_id>
```
- Parameters:
  - `limit`: Maximum similar nodes to return

### Parse Query (Without Execution)
```
POST /api/parse
```
- Body:
  - `query`: Natural language query to parse

## Example Queries

### Research Papers
- "working memory papers in frontal cortex from 2020-2023"
- "recent studies on attention and stroop task"
- "papers about emotion in amygdala"

### Brain Regions
- "brain regions involved in language processing"
- "areas connected to hippocampus"
- "frontal lobe subregions"

### Datasets & Tasks
- "datasets using n-back task"
- "fMRI studies with resting state"
- "experiments measuring executive function"

### Authors & Collaborations
- "papers by Smith about memory"
- "researchers studying fear conditioning"
- "authors who published on attention in 2023"

## Query Syntax Tips

### Temporal Filters
- Specific years: "2020-2023", "2022"
- Relative time: "recent", "last 5 years", "past decade"
- Latest research: "latest", "new", "current"

### Concept Keywords
The system recognizes common neuroscience concepts:
- Cognitive: memory, attention, emotion, language, perception
- Functions: motor, executive, learning
- Methods: fMRI, neuroimaging, activation

### Brain Region Patterns
Recognized region names and abbreviations:
- Full names: frontal cortex, hippocampus, amygdala
- Abbreviations: PFC, ACC, V1, STG
- Categories: cortex, subcortical, brainstem

## Using the Results

### Search Results View
1. Each result shows:
   - Entity type icon
   - Title/name
   - Key properties (year, journal, etc.)
   - Brief description/abstract

2. Actions per result:
   - View Details: See full node properties
   - Find Similar: Discover related entities
   - Expand Graph: Visualize connections

### Graph View
- Force-directed layout
- Color-coded by entity type
- Click nodes for details
- Drag to rearrange

### Query Details Tab
- Original query text
- Detected entity type
- Extracted filters
- Confidence score
- Generated Cypher query

## Advanced Features

### Batch Operations
1. Select multiple nodes using checkboxes
2. Use action buttons:
   - Summarize Selected
   - Export Selected
   - Clear Selection

### Query Templates
Common query patterns you can adapt:
```
"[concept] papers in [brain region] from [year range]"
"recent studies on [task1] and [task2]"
"[author] papers about [concept]"
"datasets using [task] with [participant type]"
```

### Export Formats
- CSV: Tabular data for analysis
- JSON: Full node properties
- GraphML: Network structure
- BIDS: Neuroimaging metadata

## Troubleshooting

### No Results Found
- Try broader terms (e.g., "memory" instead of "working memory")
- Check spelling of technical terms
- Remove date restrictions
- Use fewer filters

### Unexpected Results
- Check the Query Details tab
- Verify extracted filters match intent
- Try rephrasing with clearer terms
- Use the generated Cypher as a starting point

### Performance Tips
- Start with smaller result sets (Top 20)
- Add filters to narrow results
- Use specific terms when possible
- Leverage the graph view for exploration

## Integration Examples

### Python
```python
import requests

# Smart search
response = requests.post('http://localhost:5000/api/search/smart',
    json={'query': 'working memory fMRI studies', 'limit': 50})
results = response.json()

# Summarize nodes
summary = requests.post('http://localhost:5000/api/summarize',
    json={'node_ids': [node['id'] for node in results['results'][:5]]})
```

### JavaScript
```javascript
// Smart search
fetch('http://localhost:5000/api/search/smart', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        query: 'attention networks in parietal cortex',
        limit: 20
    })
})
.then(res => res.json())
.then(data => console.log(data.results));
```

## Best Practices

1. **Start Broad, Then Narrow**
   - Begin with general concepts
   - Add filters based on initial results
   - Use the graph view to explore connections

2. **Leverage Transparency**
   - Always check how your query was interpreted
   - Learn from the generated Cypher
   - Adjust query based on extracted filters

3. **Combine Search and Browse**
   - Use search for targeted queries
   - Switch to graph view for exploration
   - Find similar nodes to discover related content

4. **Save Useful Queries**
   - Copy successful Cypher queries
   - Build a library of query templates
   - Share queries with colleagues

## Future Enhancements

Planned features include:
- Query autocomplete suggestions
- Saved search alerts
- Collaborative workspaces
- Advanced visualization options
- Machine learning-based recommendations
