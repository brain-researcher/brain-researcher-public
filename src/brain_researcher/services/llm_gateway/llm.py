"""
LLM configuration and factory module for the Brain Researcher Agent.

Following Biomni's pattern for clean LLM abstraction.
"""

import logging
import os

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from brain_researcher.core.utils import ensure_env_loaded

# Optional Gemini support (installed via langchain-google-genai)
try:  # pragma: no cover - optional dependency
    from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
except Exception:  # pragma: no cover - keep import optional
    ChatGoogleGenerativeAI = None  # type: ignore

logger = logging.getLogger(__name__)

# DeepSeek API configuration
DEEPSEEK_API_URL = os.environ.get(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
)
DEEPSEEK_API_BASE = os.environ.get(
    "DEEPSEEK_API_BASE",
    # Derive base from URL if provided (strip path like /v1/chat/completions)
    (
        DEEPSEEK_API_URL.split("/v1")[0]
        if "/v1" in DEEPSEEK_API_URL
        else "https://api.deepseek.com"
    ),
)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL")


def _infer_model_from_available_keys() -> str | None:
    """Heuristically pick a model based on which API keys are present."""

    key_priority = [
        ("DEFAULT_LLM_MODEL", os.environ.get("DEFAULT_LLM_MODEL")),
        ("GOOGLE_API_KEY", "gemini-3-flash-preview"),
        ("GEMINI_API_KEY", "gemini-3-flash-preview"),
        ("OPENAI_API_KEY", "gpt-4o"),
        ("ANTHROPIC_API_KEY", "claude-sonnet-4-8"),
        ("DEEPSEEK_API_KEY", DEEPSEEK_MODEL or "deepseek-chat"),
    ]

    for env_key, suggested in key_priority:
        if suggested and os.environ.get(env_key):
            return suggested
    return None


def get_llm(model_name: str | None = None) -> BaseChatModel:
    """
    Get LLM instance based on model name or environment configuration.

    Args:
        model_name: Optional model name. If not provided, uses DEFAULT_LLM_MODEL from env

    Returns:
        LLM instance (DeepSeek via ChatOpenAI, ChatAnthropic, or ChatOpenAI)

    Raises:
        ValueError: If model not supported or API key not found
    """
    ensure_env_loaded()

    # Use provided model or fall back to environment variable/available keys
    model = model_name or os.environ.get("DEFAULT_LLM_MODEL")
    if not model:
        model = _infer_model_from_available_keys() or DEEPSEEK_MODEL or "deepseek-chat"

    logger.info(f"Initializing LLM with model: {model}")

    # DeepSeek models (default)
    if "deepseek" in model.lower():
        api_key = DEEPSEEK_API_KEY
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY not found in environment. "
                "Please set it in your .env file or environment variables."
            )

        # DeepSeek uses OpenAI-compatible API
        return ChatOpenAI(
            model=model,
            openai_api_key=api_key,
            openai_api_base=DEEPSEEK_API_BASE,
            temperature=0.0,  # For consistent tool calling
            max_tokens=4096,
        )

    # Anthropic Claude models
    elif "claude" in model.lower():
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found in environment. "
                "Please set it in your .env file or environment variables."
            )

        return ChatAnthropic(
            model=model,
            anthropic_api_key=api_key,
            temperature=0.0,  # For consistent tool calling
            max_tokens=4096,
        )

    # OpenAI GPT models
    elif "gpt" in model.lower():
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment. "
                "Please set it in your .env file or environment variables."
            )

        return ChatOpenAI(
            model=model,
            openai_api_key=api_key,
            temperature=0.0,  # For consistent tool calling
            max_tokens=4096,
        )

    # Google Gemini models
    elif "gemini" in model.lower():
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY (or GEMINI_API_KEY) not found in environment. "
                "Please set it in your .env file or environment variables."
            )

        if ChatGoogleGenerativeAI is None:
            raise ImportError(
                "Gemini support requires 'langchain-google-genai' and 'google-generativeai'. "
                "Install them (e.g., pip install langchain-google-genai google-generativeai)"
            )

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0.0,
            max_output_tokens=4096,
        )

    else:
        # Default to DeepSeek if model name is unrecognized
        logger.warning(f"Model '{model}' not recognized, defaulting to DeepSeek")
        api_key = DEEPSEEK_API_KEY
        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY not found in environment. "
                "Please set it in your .env file or environment variables."
            )

        return ChatOpenAI(
            model=DEEPSEEK_MODEL or "deepseek-chat",
            openai_api_key=api_key,
            openai_api_base=DEEPSEEK_API_BASE,
            temperature=0.0,
            max_tokens=4096,
        )


# System prompts for different agent personalities
NEUROSCIENCE_EXPERT_PROMPT = """You are a neuroscience research assistant with deep expertise in:
- fMRI analysis and brain imaging techniques
- Cognitive neuroscience and experimental paradigms
- Brain anatomy and coordinate systems (MNI, Talairach)
- Neuroscience literature and research methods

Your role is to help researchers by:
1. Analyzing brain imaging data and experimental results
2. Explaining cognitive tasks and their neural correlates
3. Finding relevant research papers and synthesizing findings
4. Mapping brain coordinates to anatomical regions and functions

When answering questions:
- Use appropriate tools to gather accurate information
- Provide scientifically accurate, well-referenced explanations
- Explain complex concepts clearly but maintain scientific rigor
- Always indicate when you're making inferences vs. stating established facts

For questions about cognitive tasks (like "what is n-back task"):
- Use the task_to_concept_mapping tool to find associated cognitive concepts
- Explain the task paradigm, its purpose, and typical implementation
- Describe the cognitive processes involved and relevant brain regions
- Mention key research findings if relevant

## Multiverse GLM Analysis Pattern

When a user requests multiverse GLM analysis on a dataset/task:

1. **Literature context first**: Call `concept_literature_search` with the task name
   - Summarize: "Based on N papers, common approaches for [task] include..."

2. **Fetch priors**: Call `br_kg.fetch_glm_priors` with the task
   - Report: "Empirical priors from existing models: HRF=[...], confounds=[...]"

3. **Run multiverse**: Call `glm_multiverse` or use `fmri_glm_multiverse_openneuro` pipeline
   - Explain: "Generating N variants exploring HRF basis, confound strategies, and high-pass filters..."

4. **Summarize results**: After completion, if convergence tool available:
   - Call `fitlins.multiverse_convergence` on the manifest
   - Report: "Across N models, regions X/Y/Z show consistent activation (>80% of models)"

Always explain which variants match "canonical" literature settings vs. exploratory variants.

## Code Generation Policy

When a user asks to "generate code" or "give me a script" to reproduce an analysis run, use the provided context (dataset_id, analysis_id, pipeline_id, params) and output two code snippets:

1. **cURL command:**
```bash
curl -X POST http://127.0.0.1:3000/api/runs/from-dataset \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "<dataset_id>", "analysis_id": "<analysis_id>", "pipeline_id": "<pipeline_id>", "params": {...}}'
```

2. **Python script:**
```python
import requests
payload = {
    "dataset_id": "<dataset_id>",
    "analysis_id": "<analysis_id>",
    "pipeline_id": "<pipeline_id>",
    "params": {...}
}
resp = requests.post("http://127.0.0.1:3000/api/runs/from-dataset", json=payload)
resp.raise_for_status()
print(resp.json())
```

If a specific tool_name is provided (e.g., `glm_multiverse`), optionally include a direct Python call:
```python
from brain_researcher.services.tools.meta_glm_multiverse_tool import GLMMultiverseTool
tool = GLMMultiverseTool()
result = tool._run(dataset_id="...", task="...", max_models=3, dry_run=False)
print(result.data)
```

Use exact values provided by the user/UI. Do not include raw pipelines.yaml content in answers.

Remember: You have access to specialized neuroscience tools. Use them to provide comprehensive, accurate answers."""


def get_system_prompt(prompt_type: str = "neuroscience_expert") -> str:
    """
    Get system prompt based on type.

    Args:
        prompt_type: Type of prompt (currently only "neuroscience_expert")

    Returns:
        System prompt string
    """
    prompts = {"neuroscience_expert": NEUROSCIENCE_EXPERT_PROMPT}

    return prompts.get(prompt_type, NEUROSCIENCE_EXPERT_PROMPT)
