#!/usr/bin/env python3
"""
LangServe application for the Brain Researcher Agent.

Note: LangChain recommends using LangGraph Platform for LangGraph-based applications.
This is a LangServe implementation for compatibility.
"""

import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableLambda
from langserve import add_routes
from pydantic import BaseModel, Field

# Create FastAPI app
app = FastAPI(
    title="Brain Researcher Agent API",
    version="1.0.0",
    description="LangServe API for neuroscience research agent",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Define input/output schemas using Pydantic
class ResearchInput(BaseModel):
    """Input for research queries."""

    query: str = Field(..., description="The research question or analysis request")


class ResearchOutput(BaseModel):
    """Output from research analysis."""

    response: str = Field(..., description="The analysis results")
    tools_used: list[str] = Field(
        default_factory=list, description="Tools used in analysis"
    )
    success: bool = Field(True, description="Whether the analysis succeeded")


# Create a simple runnable for now (to avoid import issues)
def create_research_runnable():
    """Create a runnable that processes research queries."""

    def process_research(input_data: dict[str, Any]) -> dict[str, Any]:
        """Process a research query."""
        query = input_data.get("query", "")

        # For now, return a placeholder response
        # In production, this would call your actual agent
        return {
            "response": f"Processing research query: {query}",
            "tools_used": ["placeholder"],
            "success": True,
        }

    # Create runnable with explicit types
    runnable = RunnableLambda(process_research)
    return runnable.with_types(input_type=ResearchInput, output_type=ResearchOutput)


# Create the research runnable
research_runnable = create_research_runnable()

# Add routes with LangServe
add_routes(
    app,
    research_runnable,
    path="/research",
    # Use "default" playground for general runnables
    playground_type="default",
    # Enable additional endpoints
    enable_feedback_endpoint=True,
    enable_public_trace_link_endpoint=True,
)


# Health check endpoint
@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "langserve"}


# Root endpoint
@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "name": "Brain Researcher Agent API (LangServe)",
        "version": "1.0.0",
        "docs": "/docs",
        "playground": "/research/playground",
        "endpoints": {
            "invoke": "POST /research/invoke",
            "stream": "POST /research/stream",
            "batch": "POST /research/batch",
        },
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    print("Starting Brain Researcher Agent with LangServe")
    print(f"Docs: http://localhost:{port}/docs")
    print(f"Playground: http://localhost:{port}/research/playground")

    uvicorn.run(app, host=host, port=port)
