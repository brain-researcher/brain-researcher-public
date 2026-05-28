from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator.datasets_api import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_search_endpoint_returns_results() -> None:
    response = client.get('/api/datasets/search?limit=5')
    assert response.status_code == 200
    data = response.json()
    assert data['datasets']
    assert data['total'] >= len(data['datasets'])


def test_dataset_detail_round_trip() -> None:
    search = client.get('/api/datasets/search?limit=1').json()
    dataset_id = search['datasets'][0]['id']
    detail = client.get(f'/api/datasets/{dataset_id}')
    assert detail.status_code == 200
    payload = detail.json()
    assert payload['id'] == dataset_id
    assert payload['primary_url']
    assert 'category' in payload


def test_category_filter_and_facets() -> None:
    response = client.get('/api/datasets/search?category=OpenNeuro&limit=5')
    assert response.status_code == 200
    body = response.json()
    assert body['datasets'], 'expected at least one dataset for OpenNeuro category'
    assert all(dataset.get('category') == 'OpenNeuro' for dataset in body['datasets'])
    category_facets = body['facets'].get('category', [])
    assert any(facet['value'] == 'OpenNeuro' for facet in category_facets)
