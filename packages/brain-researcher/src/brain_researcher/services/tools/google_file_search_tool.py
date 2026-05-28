"""Google File Search tool for RAG operations.

This tool implements Google's File Search API for Retrieval Augmented Generation (RAG).
It supports creating file search stores, uploading documents, and performing semantic searches
using the current file_search_stores endpoints.

API Reference: https://ai.google.dev/gemini-api/docs/file-search
"""

from __future__ import annotations

import os
import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from brain_researcher.core.grounding_references import anchors_from_gfs_hits
from brain_researcher.core.literature import gfs_store
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class FileSearchOperation(str, Enum):
    """Available operations for the Google File Search tool."""

    CREATE_STORE = "create_store"
    LIST_STORES = "list_stores"
    DELETE_STORE = "delete_store"
    UPLOAD = "upload"
    LIST_FILES = "list_files"
    DELETE_FILE = "delete_file"
    QUERY = "query"


class GoogleFileSearchArgs(BaseModel):
    """Arguments for Google File Search operations."""

    operation: FileSearchOperation = Field(
        description="Operation to perform: create_store, list_stores, delete_store, upload, list_files, delete_file, or query"
    )
    store_name: Optional[str] = Field(
        default=None,
        description="Store name/ID (required for most operations except list_stores)",
    )
    display_name: Optional[str] = Field(
        default=None,
        description="Human-readable display name for the store (used in create_store)",
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Local file path to upload (required for upload operation)",
    )
    file_name: Optional[str] = Field(
        default=None, description="File name/ID in the store (required for delete_file)"
    )
    query: Optional[str] = Field(
        default=None,
        description="Search query for semantic search (required for query operation)",
    )
    metadata_filter: Optional[str] = Field(
        default=None,
        description="Optional metadata filter expression for query operation",
    )
    max_tokens_per_chunk: Optional[int] = Field(
        default=256, description="Maximum tokens per chunk for upload (default: 256)"
    )
    max_overlap_tokens: Optional[int] = Field(
        default=64, description="Token overlap between chunks for upload (default: 64)"
    )
    top_k: Optional[int] = Field(
        default=10, description="Number of results to return for query (default: 10)"
    )
    page_size: Optional[int] = Field(
        default=100,
        description="Maximum items to return for list_stores/list_files/query (default: 100)",
    )
    page_token: Optional[str] = Field(
        default=None, description="Page token for pagination (optional)"
    )


class GoogleFileSearchTool(NeuroToolWrapper):
    """Google File Search tool for RAG operations.

    This tool provides access to Google's File Search API, enabling:
    - Creation and management of file stores (vector stores)
    - Uploading documents with configurable chunking
    - Semantic search across uploaded documents
    - Metadata filtering for refined search results

    Requires google-genai SDK and GOOGLE_API_KEY or GEMINI_API_KEY environment variable.
    """

    DANGEROUS = True  # Can create/delete stores and files
    TAGS = ["rag", "search", "gemini", "google"]
    COST_HINT = "normal"

    def __init__(self):
        super().__init__()
        self._client = None

    def _get_client(self):
        """Lazily initialize the Google GenAI client."""
        if self._client is None:
            try:
                from google import genai
            except ImportError:
                raise ImportError(
                    "google-genai package not installed. Run: pip install google-genai"
                )

            api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get(
                "GEMINI_API_KEY"
            )
            if not api_key:
                raise ValueError(
                    "GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set"
                )

            self._client = genai.Client(api_key=api_key)
        return self._client

    def get_tool_name(self) -> str:
        return "google.file_search"

    def get_tool_description(self) -> str:
        return (
            "RAG operations via Google File Search API. Supports: create_store (create vector store), "
            "list_stores (list all stores), delete_store (remove store), upload (add file with chunking), "
            "list_files (list files in store), delete_file (remove file), query (semantic search). "
            "Query results include summary text, structured hits, and typed anchors. "
            "For evidence_basis.reference, copy an anchor_id exactly; do not compose free-form references. "
            "Requires GOOGLE_API_KEY or GEMINI_API_KEY environment variable."
        )

    def get_args_schema(self):
        return GoogleFileSearchArgs

    def _run(
        self,
        operation: FileSearchOperation,
        store_name: Optional[str] = None,
        display_name: Optional[str] = None,
        file_path: Optional[str] = None,
        file_name: Optional[str] = None,
        query: Optional[str] = None,
        metadata_filter: Optional[str] = None,
        max_tokens_per_chunk: int = 256,
        max_overlap_tokens: int = 64,
        top_k: int = 10,
        page_size: int = 100,
        page_token: Optional[str] = None,
    ) -> ToolResult:
        """Execute the requested file search operation."""

        # Convert string to enum if needed
        if isinstance(operation, str):
            operation = FileSearchOperation(operation)

        try:
            if operation == FileSearchOperation.QUERY:
                return self._query_store(
                    None,
                    store_name,
                    query,
                    metadata_filter,
                    top_k,
                    page_size,
                    page_token,
                )

            client = self._get_client()

            if operation == FileSearchOperation.CREATE_STORE:
                return self._create_store(client, store_name, display_name)
            elif operation == FileSearchOperation.LIST_STORES:
                return self._list_stores(
                    client, page_size=page_size, page_token=page_token
                )
            elif operation == FileSearchOperation.DELETE_STORE:
                return self._delete_store(client, store_name)
            elif operation == FileSearchOperation.UPLOAD:
                return self._upload_file(
                    client,
                    store_name,
                    file_path,
                    max_tokens_per_chunk,
                    max_overlap_tokens,
                )
            elif operation == FileSearchOperation.LIST_FILES:
                return self._list_files(
                    client, store_name, page_size=page_size, page_token=page_token
                )
            elif operation == FileSearchOperation.DELETE_FILE:
                return self._delete_file(client, store_name, file_name)
            else:
                return ToolResult(
                    status="error", error=f"Unknown operation: {operation}"
                )

        except ImportError as e:
            return ToolResult(
                status="error", error=str(e), metadata={"error_type": "ImportError"}
            )
        except ValueError as e:
            return ToolResult(
                status="error", error=str(e), metadata={"error_type": "ValueError"}
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"File search operation failed: {str(e)}",
                metadata={
                    "error_type": type(e).__name__,
                    "operation": str(operation),
                    "store_name": store_name,
                },
            )

    @staticmethod
    def _normalize_store_name(store_name: str) -> str:
        if not store_name:
            return store_name
        return (
            store_name
            if store_name.startswith("fileSearchStores/")
            else f"fileSearchStores/{store_name}"
        )

    def _poll_operation(self, client, operation, timeout_seconds: int = 120):
        """Poll a long-running operation until done or timeout."""
        start = time.time()
        while not operation.done:
            if time.time() - start > timeout_seconds:
                raise TimeoutError("File search operation timed out")
            time.sleep(5)
            operation = client.operations.get(operation)
        return operation

    def _create_store(
        self, client, store_name: Optional[str], display_name: Optional[str]
    ) -> ToolResult:
        """Create a new file search store."""
        if not store_name:
            return ToolResult(
                status="error",
                error="store_name is required for create_store operation",
            )

        resp = client.file_search_stores.create(
            config={"display_name": display_name or store_name}
        )

        return ToolResult(
            status="success",
            data={
                "store_name": resp.name,
                "display_name": getattr(resp, "display_name", None),
                "created": True,
            },
        )

    def _list_stores(
        self, client, page_size: int = 100, page_token: Optional[str] = None
    ) -> ToolResult:
        """List all available file search stores.

        Note: newer google-genai SDKs no longer accept page_size/page_token for list();
        passing them can raise INVALID_ARGUMENT. We therefore call list() without args
        and slice locally for backward compatibility.
        """
        stores_resp = list(client.file_search_stores.list())
        if page_token:
            # client.list() no longer supports page_token; ignore gracefully
            pass
        if page_size:
            stores_resp = stores_resp[: max(1, page_size)]

        stores = []
        for store in stores_resp:
            stores.append(
                {
                    "name": store.name,
                    "display_name": getattr(store, "display_name", None),
                    "active_documents": getattr(store, "active_documents_count", None),
                    "pending_documents": getattr(
                        store, "pending_documents_count", None
                    ),
                }
            )

        return ToolResult(
            status="success",
            data={
                "stores": stores,
                "count": len(stores),
                "page_size": page_size,
                "page_token": page_token,
            },
        )

    def _delete_store(self, client, store_name: Optional[str]) -> ToolResult:
        """Delete a file search store."""
        if not store_name:
            return ToolResult(
                status="error",
                error="store_name is required for delete_store operation",
            )

        store_name = self._normalize_store_name(store_name)
        client.file_search_stores.delete(name=store_name)

        return ToolResult(
            status="success", data={"store_name": store_name, "deleted": True}
        )

    def _upload_file(
        self,
        client,
        store_name: Optional[str],
        file_path: Optional[str],
        max_tokens_per_chunk: int,
        max_overlap_tokens: int,
    ) -> ToolResult:
        """Upload a file to a store with chunking configuration."""
        if not store_name:
            return ToolResult(
                status="error", error="store_name is required for upload operation"
            )
        if not file_path:
            return ToolResult(
                status="error", error="file_path is required for upload operation"
            )
        if not os.path.exists(file_path):
            return ToolResult(status="error", error=f"File not found: {file_path}")
        # basic safety: cap file size to ~25MB
        if os.path.getsize(file_path) > 25 * 1024 * 1024:
            return ToolResult(
                status="error",
                error="File too large (>25MB); please provide a smaller file",
            )

        store_name = self._normalize_store_name(store_name)

        chunk_cfg = {
            "white_space_config": {
                "max_tokens_per_chunk": max_tokens_per_chunk,
                "max_overlap_tokens": max_overlap_tokens,
            }
        }

        op = client.file_search_stores.upload_to_file_search_store(
            file=file_path,
            file_search_store_name=store_name,
            config={
                "display_name": os.path.basename(file_path),
                "chunking_config": chunk_cfg,
            },
        )

        op = self._poll_operation(client, op)

        return ToolResult(
            status="success",
            data={
                "store_name": store_name,
                "file_path": file_path,
                "uploaded": True,
                "operation_name": getattr(op, "name", None),
                "chunk_config": {
                    "max_tokens_per_chunk": max_tokens_per_chunk,
                    "max_overlap_tokens": max_overlap_tokens,
                },
            },
        )

    def _list_files(
        self,
        client,
        store_name: Optional[str],
        page_size: int = 100,
        page_token: Optional[str] = None,
    ) -> ToolResult:
        """List all files in a store.

        New SDK versions ignore page_size/page_token; we slice client output locally.
        """
        if not store_name:
            return ToolResult(
                status="error", error="store_name is required for list_files operation"
            )

        store_name = self._normalize_store_name(store_name)
        documents = list(client.file_search_stores.files.list(parent=store_name))
        if page_size:
            documents = documents[: max(1, page_size)]

        files = []
        for doc in documents:
            files.append(
                {
                    "name": doc.name,
                    "display_name": getattr(doc, "display_name", None),
                }
            )

        return ToolResult(
            status="success",
            data={
                "store_name": store_name,
                "files": files,
                "count": len(files),
                "page_size": page_size,
                "page_token": page_token,
            },
        )

    def _delete_file(
        self, client, store_name: Optional[str], file_name: Optional[str]
    ) -> ToolResult:
        """Delete a file from a store."""
        if not store_name:
            return ToolResult(
                status="error", error="store_name is required for delete_file operation"
            )
        if not file_name:
            return ToolResult(
                status="error", error="file_name is required for delete_file operation"
            )

        store_name = self._normalize_store_name(store_name)

        # Construct the full document name if not provided
        if not file_name.startswith("fileSearchStores/"):
            doc_name = f"{store_name}/files/{file_name}"
        else:
            doc_name = file_name

        client.file_search_stores.files.delete(name=doc_name)

        return ToolResult(
            status="success",
            data={"store_name": store_name, "file_name": file_name, "deleted": True},
        )

    @staticmethod
    def _reference_from_hit(hit: dict[str, Any]) -> dict[str, Any] | None:
        """Return a benchmark-friendly reference anchor for a structured hit."""
        doi = (hit.get("doi") or "").strip()
        if doi:
            return {
                "reference_type": "doi",
                "reference": f"doi:{doi}",
                "title": hit.get("title"),
                "snippet": hit.get("snippet"),
                "score": hit.get("score"),
                "doc_id": hit.get("doc_id"),
            }
        pmid = (hit.get("pmid") or "").strip()
        if pmid:
            return {
                "reference_type": "pmid",
                "reference": f"pmid:{pmid}",
                "title": hit.get("title"),
                "snippet": hit.get("snippet"),
                "score": hit.get("score"),
                "doc_id": hit.get("doc_id"),
            }
        pmcid = (hit.get("pmcid") or "").strip()
        if pmcid:
            return {
                "reference_type": "pmcid",
                "reference": f"pmcid:{pmcid}",
                "title": hit.get("title"),
                "snippet": hit.get("snippet"),
                "score": hit.get("score"),
                "doc_id": hit.get("doc_id"),
            }
        doc_id = (hit.get("doc_id") or "").strip()
        if doc_id:
            reference = doc_id if doc_id.startswith("doc:") else f"doc:{doc_id}"
            return {
                "reference_type": "document",
                "reference": reference,
                "title": hit.get("title"),
                "snippet": hit.get("snippet"),
                "score": hit.get("score"),
                "doc_id": doc_id,
            }
        return None

    @classmethod
    def _references_from_hits(cls, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        seen: set[str] = set()
        for hit in hits:
            ref = cls._reference_from_hit(hit)
            if not ref:
                continue
            reference = str(ref.get("reference") or "")
            if not reference or reference in seen:
                continue
            seen.add(reference)
            references.append(ref)
        return references

    def _query_store(
        self,
        client,
        store_name: Optional[str],
        query: Optional[str],
        metadata_filter: Optional[str],
        top_k: int,
        page_size: int = 100,
        page_token: Optional[str] = None,
    ) -> ToolResult:
        """Perform semantic search across store documents."""
        if not store_name:
            return ToolResult(
                status="error", error="store_name is required for query operation"
            )
        if not query:
            return ToolResult(
                status="error", error="query is required for query operation"
            )

        store_name = self._normalize_store_name(store_name)
        result = gfs_store.search_gfs(
            query,
            store=store_name,
            top_k=top_k,
        )
        if result.get("status") != "ok":
            error = result.get("error") or result.get("reason") or result.get("status")
            return ToolResult(
                status="error",
                error=str(error),
                data=result,
            )

        hits = list(result.get("hits") or [])
        anchors = list(result.get("anchors") or []) or anchors_from_gfs_hits(hits)
        references = self._references_from_hits(hits)
        summary = str(result.get("summary") or "")

        return ToolResult(
            status="success",
            data={
                "store_name": store_name,
                "query": query,
                "results": summary,
                "summary": summary,
                "hits": hits,
                "anchors": anchors,
                "references": references,
                "grounding": {
                    "reference_count": len(references),
                    "anchor_count": len(anchors),
                    "hit_count": len(hits),
                    "raw_hit_count": result.get("raw_hit_count"),
                    "n_docs_hit": result.get("n_docs_hit"),
                    "stores_attempted": result.get("stores_attempted"),
                    "stores_hit": result.get("stores_hit"),
                    "model": result.get("model"),
                    "anchor_policy": (
                        "Use evidence_basis.reference only by copying an anchor_id. "
                        "Use basis_type=specific_citation for doi:/pmid:/pmcid: anchors "
                        "and basis_type=retrieved_document for doc:/document: anchors."
                    ),
                },
                "page_size": page_size,
                "page_token": page_token,
            },
            metadata={
                "operation": "query",
                "metadata_filter_ignored": bool(metadata_filter),
                "call_count": result.get("call_count"),
                "latency_ms": result.get("latency_ms"),
                "store_errors": result.get("store_errors"),
            },
        )


def get_all_tools():
    """Return all Google file search tools."""
    return [GoogleFileSearchTool()]
