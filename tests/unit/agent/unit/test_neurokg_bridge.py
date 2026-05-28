from unittest.mock import Mock, patch

import requests

from brain_researcher.services.tools import neurokg_bridge


@patch("requests.post")
def test_post_with_retry_success(mock_post):
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"ok": True}
    mock_post.return_value = mock_resp

    result = neurokg_bridge.post_with_retry("http://api", {"q": 1}, retries=2)

    assert result["status"] == "success"
    assert result["data"] == {"ok": True}
    mock_post.assert_called_once()


@patch("requests.post")
def test_post_with_retry_failure(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    result = neurokg_bridge.post_with_retry("http://api", {}, retries=2)

    assert result["status"] == "error"
    assert "boom" in result["error"]
    assert mock_post.call_count == 3  # initial try + 2 retries
