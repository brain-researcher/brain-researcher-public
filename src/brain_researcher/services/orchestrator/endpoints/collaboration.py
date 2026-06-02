"""
Collaboration and real-time features API endpoints
"""

import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)
        self.user_info: Dict[str, Dict] = {}
        self.document_users: Dict[str, set] = defaultdict(set)

    async def connect(
        self, websocket: WebSocket, document_id: str, user_id: str, user_name: str
    ):
        await websocket.accept()
        self.active_connections[document_id].append(websocket)
        self.user_info[user_id] = {
            "id": user_id,
            "name": user_name,
            "websocket": websocket,
            "document_id": document_id,
            "status": "online",
            "connected_at": datetime.now(),
        }
        self.document_users[document_id].add(user_id)

    def disconnect(self, websocket: WebSocket, document_id: str, user_id: str):
        self.active_connections[document_id].remove(websocket)
        if user_id in self.user_info:
            del self.user_info[user_id]
        self.document_users[document_id].discard(user_id)

    async def broadcast_to_document(
        self, document_id: str, message: dict, exclude_user: Optional[str] = None
    ):
        for websocket in self.active_connections[document_id]:
            try:
                user_id = self._get_user_id_by_websocket(websocket, document_id)
                if user_id != exclude_user:
                    await websocket.send_json(message)
            except:
                pass

    def _get_user_id_by_websocket(
        self, websocket: WebSocket, document_id: str
    ) -> Optional[str]:
        for user_id, info in self.user_info.items():
            if info["websocket"] == websocket and info["document_id"] == document_id:
                return user_id
        return None

    def get_document_users(self, document_id: str) -> List[Dict]:
        users = []
        for user_id in self.document_users[document_id]:
            if user_id in self.user_info:
                info = self.user_info[user_id].copy()
                info.pop("websocket", None)
                users.append(info)
        return users


manager = ConnectionManager()


# Models
class Comment(BaseModel):
    content: str
    parent_id: Optional[str] = None
    document_id: str
    position: Optional[Dict[str, Any]] = None


class CommentResponse(BaseModel):
    id: str
    user_id: str
    user_name: str
    content: str
    timestamp: datetime
    parent_id: Optional[str] = None
    replies: List["CommentResponse"] = []
    likes: int = 0
    resolved: bool = False


class SharePermission(BaseModel):
    email: str
    role: str = Field(..., pattern="^(viewer|editor|owner)$")
    expires_at: Optional[datetime] = None


class SearchFilter(BaseModel):
    field: str
    operator: str
    value: Any
    type: str = Field(..., pattern="^(text|number|boolean|date|select)$")


class SearchQuery(BaseModel):
    filters: List[SearchFilter]
    sort_by: Optional[str] = "relevance"
    sort_order: Optional[str] = Field("desc", pattern="^(asc|desc)$")
    limit: Optional[int] = Field(20, ge=1, le=100)
    offset: Optional[int] = Field(0, ge=0)


class SavedSearch(BaseModel):
    name: str
    query: SearchQuery


# In-memory storage (replace with database in production)
comments_store: Dict[str, List[CommentResponse]] = defaultdict(list)
permissions_store: Dict[str, List[SharePermission]] = defaultdict(list)
saved_searches_store: Dict[str, List[Dict]] = defaultdict(list)


# WebSocket endpoint for real-time collaboration
@router.websocket("/ws/{document_id}")
async def websocket_endpoint(websocket: WebSocket, document_id: str):
    user_id = str(uuid.uuid4())  # In production, get from auth
    user_name = "User"  # In production, get from auth

    await manager.connect(websocket, document_id, user_id, user_name)

    try:
        # Send initial users list
        await websocket.send_json(
            {"type": "users", "users": manager.get_document_users(document_id)}
        )

        # Notify others of new user
        await manager.broadcast_to_document(
            document_id,
            {
                "type": "user_joined",
                "userId": user_id,
                "userName": user_name,
                "timestamp": datetime.now().isoformat(),
            },
            exclude_user=user_id,
        )

        while True:
            data = await websocket.receive_json()

            # Handle different message types
            if data["type"] == "ping":
                await websocket.send_json({"type": "pong"})

            elif data["type"] == "cursor":
                await manager.broadcast_to_document(
                    document_id,
                    {
                        "type": "cursor",
                        "userId": user_id,
                        "userName": user_name,
                        "x": data["x"],
                        "y": data["y"],
                        "timestamp": data["timestamp"],
                    },
                    exclude_user=user_id,
                )

            elif data["type"] == "selection":
                await manager.broadcast_to_document(
                    document_id,
                    {
                        "type": "selection",
                        "userId": user_id,
                        "userName": user_name,
                        **data,
                    },
                    exclude_user=user_id,
                )

            elif data["type"] == "edit":
                await manager.broadcast_to_document(
                    document_id,
                    {"type": "edit", "userId": user_id, "userName": user_name, **data},
                    exclude_user=user_id,
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket, document_id, user_id)

        # Notify others of user leaving
        await manager.broadcast_to_document(
            document_id,
            {
                "type": "user_left",
                "userId": user_id,
                "userName": user_name,
                "timestamp": datetime.now().isoformat(),
            },
        )


# Comments endpoints
@router.post("/comments")
async def create_comment(comment: Comment):
    """Create a new comment"""
    comment_id = str(uuid.uuid4())
    user_id = "user_1"  # In production, get from auth
    user_name = "Current User"  # In production, get from auth

    comment_response = CommentResponse(
        id=comment_id,
        user_id=user_id,
        user_name=user_name,
        content=comment.content,
        timestamp=datetime.now(),
        parent_id=comment.parent_id,
    )

    comments_store[comment.document_id].append(comment_response)

    # Broadcast to connected users
    await manager.broadcast_to_document(
        comment.document_id,
        {"type": "new_comment", "comment": comment_response.model_dump()},
    )

    return comment_response


@router.get("/comments/{document_id}")
async def get_comments(document_id: str):
    """Get all comments for a document"""
    comments = comments_store.get(document_id, [])

    # Build comment tree
    comment_dict = {c.id: c for c in comments}
    root_comments = []

    for comment in comments:
        if comment.parent_id and comment.parent_id in comment_dict:
            parent = comment_dict[comment.parent_id]
            parent.replies.append(comment)
        elif not comment.parent_id:
            root_comments.append(comment)

    return root_comments


@router.put("/comments/{comment_id}/resolve")
async def resolve_comment(comment_id: str, resolved: bool = True):
    """Mark a comment as resolved"""
    for doc_comments in comments_store.values():
        for comment in doc_comments:
            if comment.id == comment_id:
                comment.resolved = resolved
                return comment

    raise HTTPException(status_code=404, detail="Comment not found")


# Sharing endpoints
@router.post("/share/{document_id}")
async def share_document(document_id: str, permissions: List[SharePermission]):
    """Share a document with users"""
    permissions_store[document_id].extend(permissions)

    # Send email invitations (mock)
    for permission in permissions:
        print(f"Sending invitation to {permission.email} with {permission.role} role")

    return {"status": "success", "shared_with": len(permissions)}


@router.get("/share/{document_id}")
async def get_share_permissions(document_id: str):
    """Get sharing permissions for a document"""
    return permissions_store.get(document_id, [])


@router.delete("/share/{document_id}/{email}")
async def revoke_share(document_id: str, email: str):
    """Revoke sharing permission"""
    if document_id in permissions_store:
        permissions_store[document_id] = [
            p for p in permissions_store[document_id] if p.email != email
        ]
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="Document not found")


# Advanced search endpoints
@router.post("/search")
async def advanced_search(query: SearchQuery):
    """Execute advanced search query"""
    # Mock search implementation
    results = []

    # Apply filters
    for i in range(min(query.limit, 20)):
        results.append(
            {
                "id": f"result_{i}",
                "name": f"Result {i}",
                "type": "dataset",
                "created_at": datetime.now().isoformat(),
                "relevance_score": 1.0 - (i * 0.05),
            }
        )

    return {
        "results": results,
        "total": 100,  # Mock total
        "offset": query.offset,
        "limit": query.limit,
    }


@router.post("/search/save")
async def save_search(search: SavedSearch):
    """Save a search query"""
    user_id = "user_1"  # In production, get from auth

    saved = {
        "id": str(uuid.uuid4()),
        "name": search.name,
        "query": search.query.model_dump(),
        "created_at": datetime.now().isoformat(),
        "user_id": user_id,
    }

    saved_searches_store[user_id].append(saved)
    return saved


@router.get("/search/saved")
async def get_saved_searches():
    """Get user's saved searches"""
    user_id = "user_1"  # In production, get from auth
    return saved_searches_store.get(user_id, [])


@router.delete("/search/saved/{search_id}")
async def delete_saved_search(search_id: str):
    """Delete a saved search"""
    user_id = "user_1"  # In production, get from auth

    if user_id in saved_searches_store:
        saved_searches_store[user_id] = [
            s for s in saved_searches_store[user_id] if s["id"] != search_id
        ]
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="Search not found")


# PWA support endpoints
@router.get("/pwa/manifest")
async def get_manifest():
    """Get PWA manifest with dynamic values"""
    manifest = {
        "name": "Brain Researcher",
        "short_name": "BrainRes",
        "description": "Neuroimaging Analysis Platform",
        "theme_color": "#3B82F6",
        "background_color": "#ffffff",
        "display": "standalone",
        "orientation": "portrait",
        "scope": "/",
        "start_url": "/",
        "icons": [
            {"src": "/icons/icon-192x192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icons/icon-512x512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    return JSONResponse(content=manifest)


@router.post("/pwa/subscribe")
async def subscribe_push_notifications(subscription: Dict[str, Any]):
    """Subscribe to push notifications"""
    # Store subscription endpoint
    user_id = "user_1"  # In production, get from auth

    # In production, store in database
    print(f"User {user_id} subscribed to push notifications")

    return {"status": "subscribed"}


@router.post("/pwa/sync")
async def sync_offline_data(data: List[Dict[str, Any]]):
    """Sync offline data when connection restored"""
    synced_count = 0

    for item in data:
        # Process each offline action
        if item["type"] == "comment":
            # Create comment
            synced_count += 1
        elif item["type"] == "edit":
            # Apply edit
            synced_count += 1

    return {"synced": synced_count, "failed": len(data) - synced_count}


# User presence endpoints
@router.get("/presence/{document_id}")
async def get_document_presence(document_id: str):
    """Get active users for a document"""
    return {
        "users": manager.get_document_users(document_id),
        "total": len(manager.document_users[document_id]),
    }


@router.post("/presence/heartbeat")
async def update_presence(document_id: str, status: str = "online"):
    """Update user presence status"""
    user_id = "user_1"  # In production, get from auth

    if user_id in manager.user_info:
        manager.user_info[user_id]["status"] = status
        manager.user_info[user_id]["last_seen"] = datetime.now()

    return {"status": "updated"}
