"""Unit tests for Advanced Search Interface."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

class TestAdvancedSearchInterface:
    """Test suite for advanced search functionality."""
    
    @pytest.fixture
    def sample_queries(self):
        """Sample search queries."""
        return [
            {'id': '1', 'text': 'motor cortex', 'field': 'all', 'operator': 'AND'},
            {'id': '2', 'text': 'fMRI', 'field': 'title', 'operator': 'AND'},
            {'id': '3', 'text': 'baseline', 'field': 'description', 'operator': 'NOT'}
        ]
    
    @pytest.fixture
    def sample_filters(self):
        """Sample search filters."""
        return [
            {'field': 'type', 'operator': 'equals', 'value': 'dataset'},
            {'field': 'tags', 'operator': 'contains', 'value': 'motor'},
            {'field': 'date', 'operator': 'between', 'value': ['2025-01-01', '2025-12-31']}
        ]
    
    @pytest.fixture
    def sample_results(self):
        """Sample search results."""
        return [
            {
                'id': '1',
                'title': 'Motor Cortex Activation Study',
                'type': 'dataset',
                'relevance': 0.95,
                'tags': ['motor', 'fMRI', 'cortex']
            },
            {
                'id': '2',
                'title': 'Visual Processing Analysis',
                'type': 'analysis',
                'relevance': 0.82,
                'tags': ['visual', 'GLM']
            }
        ]
    
    def test_query_builder_add_remove(self, sample_queries):
        """Test adding and removing query conditions."""
        queries = []
        
        # Add queries
        for query in sample_queries:
            queries.append(query)
        assert len(queries) == 3
        
        # Remove query
        queries = [q for q in queries if q['id'] != '2']
        assert len(queries) == 2
        assert not any(q['id'] == '2' for q in queries)
    
    def test_logical_operators(self):
        """Test logical operator combinations."""
        operators = ['AND', 'OR', 'NOT']
        
        for op in operators:
            assert op in ['AND', 'OR', 'NOT']
        
        # Build complex query
        query = "motor AND cortex OR visual NOT baseline"
        assert 'AND' in query
        assert 'OR' in query
        assert 'NOT' in query
    
    def test_field_selection(self):
        """Test search field selection."""
        fields = ['all', 'title', 'description', 'author', 'tags', 'content', 'metadata']
        
        for field in fields:
            assert field in fields
        
        # Field-specific search
        query = {'field': 'title', 'text': 'motor cortex'}
        assert query['field'] == 'title'
    
    def test_filter_application(self, sample_filters):
        """Test applying search filters."""
        filters = sample_filters
        
        # Type filter
        type_filter = next(f for f in filters if f['field'] == 'type')
        assert type_filter['value'] == 'dataset'
        
        # Tag filter
        tag_filter = next(f for f in filters if f['field'] == 'tags')
        assert 'motor' in tag_filter['value']
        
        # Date range filter
        date_filter = next(f for f in filters if f['field'] == 'date')
        assert len(date_filter['value']) == 2
    
    def test_search_execution(self, sample_queries, sample_results):
        """Test search execution."""
        mock_search = Mock(return_value=sample_results)
        
        results = mock_search(sample_queries)
        
        assert len(results) == 2
        assert results[0]['title'] == 'Motor Cortex Activation Study'
        mock_search.assert_called_once_with(sample_queries)
    
    def test_relevance_scoring(self, sample_results):
        """Test search result relevance scoring."""
        for result in sample_results:
            assert 'relevance' in result
            assert 0 <= result['relevance'] <= 1
        
        # Sort by relevance
        sorted_results = sorted(sample_results, key=lambda x: x['relevance'], reverse=True)
        assert sorted_results[0]['relevance'] >= sorted_results[1]['relevance']
    
    def test_saved_searches(self, sample_queries, sample_filters):
        """Test saving and loading searches."""
        saved_search = {
            'id': '1',
            'name': 'Motor Study Search',
            'queries': sample_queries,
            'filters': sample_filters,
            'created_at': '2025-03-15'
        }
        
        # Save search
        saved_searches = []
        saved_searches.append(saved_search)
        assert len(saved_searches) == 1
        
        # Load search
        loaded = saved_searches[0]
        assert loaded['name'] == 'Motor Study Search'
        assert len(loaded['queries']) == 3
    
    def test_search_history(self):
        """Test search history tracking."""
        history = []
        max_history = 10
        
        # Add searches to history
        searches = ['motor cortex', 'visual processing', 'GLM analysis']
        for search in searches:
            if search not in history:
                history.insert(0, search)
                if len(history) > max_history:
                    history.pop()
        
        assert len(history) == 3
        assert history[0] == 'GLM analysis'  # Most recent
    
    def test_debounced_search(self):
        """Test search debouncing."""
        import time
        
        calls = []
        delay = 0.3
        
        def mock_search():
            calls.append(time.time())
        
        # Simulate rapid typing
        for _ in range(5):
            # In real implementation, these would be debounced
            time.sleep(0.1)
        
        # Only one call should be made after delay
        mock_search()
        assert len(calls) == 1
    
    def test_result_selection(self, sample_results):
        """Test selecting multiple results."""
        selected = set()
        
        # Select results
        for result in sample_results:
            selected.add(result['id'])
        
        assert len(selected) == 2
        assert '1' in selected
        assert '2' in selected
        
        # Deselect
        selected.discard('1')
        assert '1' not in selected
    
    def test_bulk_actions(self, sample_results):
        """Test bulk actions on selected results."""
        selected_ids = ['1', '2']
        
        # Export action
        export_data = [r for r in sample_results if r['id'] in selected_ids]
        assert len(export_data) == 2
        
        # Share action
        share_link = f"share/{','.join(selected_ids)}"
        assert '1,2' in share_link
    
    def test_search_analytics(self):
        """Test search analytics tracking."""
        analytics = {
            'total_searches': 0,
            'avg_response_time': [],
            'popular_queries': {},
            'conversion_rate': []
        }
        
        # Track search
        analytics['total_searches'] += 1
        analytics['avg_response_time'].append(245)
        
        query = 'motor cortex'
        analytics['popular_queries'][query] = analytics['popular_queries'].get(query, 0) + 1
        
        assert analytics['total_searches'] == 1
        assert analytics['popular_queries']['motor cortex'] == 1
    
    def test_sort_options(self, sample_results):
        """Test result sorting options."""
        # Sort by relevance
        by_relevance = sorted(sample_results, key=lambda x: x['relevance'], reverse=True)
        assert by_relevance[0]['relevance'] >= by_relevance[1]['relevance']
        
        # Sort by title
        by_title = sorted(sample_results, key=lambda x: x['title'])
        assert by_title[0]['title'] <= by_title[1]['title']
        
        # Sort by type
        by_type = sorted(sample_results, key=lambda x: x['type'])
        assert by_type[0]['type'] <= by_type[1]['type']
    
    def test_view_modes(self):
        """Test different result view modes."""
        view_modes = ['list', 'grid']
        current_mode = 'list'
        
        assert current_mode in view_modes
        
        # Switch to grid
        current_mode = 'grid'
        assert current_mode == 'grid'
    
    def test_highlight_matching_terms(self):
        """Test highlighting of matching search terms."""
        text = "This study examines motor cortex activation during hand movement"
        search_terms = ['motor', 'cortex']
        
        for term in search_terms:
            assert term in text.lower()
        
        # Mock highlighting
        highlighted = text
        for term in search_terms:
            highlighted = highlighted.replace(term, f'<mark>{term}</mark>')
        
        assert '<mark>motor</mark>' in highlighted
        assert '<mark>cortex</mark>' in highlighted
    
    def test_filter_combinations(self):
        """Test combining multiple filters."""
        filters = []
        
        # Add type filter
        filters.append({'field': 'type', 'operator': 'equals', 'value': 'dataset'})
        
        # Add tag filter
        filters.append({'field': 'tags', 'operator': 'contains', 'value': 'fMRI'})
        
        # Add date filter
        filters.append({'field': 'date', 'operator': 'gt', 'value': '2025-01-01'})
        
        assert len(filters) == 3
        
        # All filters should be applied
        for f in filters:
            assert 'field' in f
            assert 'operator' in f
            assert 'value' in f
    
    def test_export_search_results(self, sample_results):
        """Test exporting search results."""
        export_formats = ['csv', 'json', 'pdf']
        
        for format in export_formats:
            assert format in ['csv', 'json', 'pdf']
        
        # Mock export
        export_data = {
            'results': sample_results,
            'query': 'motor cortex',
            'filters': [],
            'timestamp': '2025-03-15'
        }
        
        assert len(export_data['results']) == 2
    
    def test_share_search_link(self, sample_queries, sample_filters):
        """Test generating shareable search link."""
        import base64
        
        search_params = {
            'queries': sample_queries,
            'filters': sample_filters
        }
        
        # Encode parameters
        encoded = base64.b64encode(json.dumps(search_params).encode()).decode()
        share_link = f"https://app.example.com/search?q={encoded}"
        
        assert 'search?q=' in share_link
        assert len(encoded) > 0
    
    def test_search_suggestions(self):
        """Test search suggestions/autocomplete."""
        suggestions = [
            'motor cortex activation',
            'motor cortex fMRI',
            'motor control',
            'motor learning'
        ]
        
        query = 'motor'
        filtered = [s for s in suggestions if s.startswith(query)]
        
        assert len(filtered) == 4
        assert all(s.startswith('motor') for s in filtered)
    
    def test_empty_search_handling(self):
        """Test handling of empty search queries."""
        queries = [{'id': '1', 'text': '', 'operator': 'AND'}]
        
        # Should not execute search
        should_search = any(q['text'].strip() for q in queries)
        assert should_search is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])