# DeepSeek client with async/sync support for chat completions
import asyncio
import json
import os
import re

import httpx
import requests

DEEPSEEK_API_URL = os.environ.get(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

SYSTEM_PROMPT = (
    "You are an expert neuroimaging assistant. "
    "You must answer ONLY in the following JSON format, with NO extra text, NO code block, and NO explanation. "
    "Here are some examples:\n"
    "User: Compare group control vs patient\n"
    "{\n"
    '  "tool": "statistical_analysis",\n'
    '  "params": {"analysis_type": "group_comparison", "group1": "control", "group2": "patient"},\n'
    '  "reasoning": "The instruction requests a group comparison between control and patient groups."\n'
    "}\n"
    "User: Generate fmriprep command for BIDS /data/bids output /data/out participant 01\n"
    "{\n"
    '  "tool": "fmriprep_command_generation",\n'
    '  "params": {"bids_dir": "/data/bids", "output_dir": "/data/out", "participant_label": ["01"]},\n'
    '  "reasoning": "The instruction requests generation of an fMRIPrep command for preprocessing BIDS data."\n'
    "}\n"
    "Now, answer the next user query in the same JSON format, with no extra text."
)


def call_deepseek_api(prompt: str, model: str = None):
    """
    Call the real DeepSeek API with the given prompt and return the response as JSON.
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set.")

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or "deepseek-chat",  # Replace with actual model name if needed
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = requests.post(
            DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60
        )
        response.raise_for_status()
        data = response.json()
        # DeepSeek API returns choices[0].message.content
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        return json.dumps(
            {
                "tool": "error",
                "params": {"message": f"DeepSeek API call failed: {str(e)}"},
                "reasoning": "Failed to call DeepSeek API.",
            }
        )


def parse_llm_response(response_raw: str):
    print("\n[DEBUG] Raw LLM output:\n" + response_raw + "\n")
    try:
        # Try to extract the first {...} JSON block
        match = re.search(r"\{[\s\S]*\}", response_raw)
        if match:
            data = json.loads(match.group(0))
        else:
            data = json.loads(response_raw)
        return {
            "tool": data.get("tool"),
            "params": data.get("params", {}),
            "reasoning": data.get("reasoning", ""),
        }
    except Exception:
        return {
            "tool": "error",
            "params": {"message": "Failed to parse LLM response as JSON"},
            "reasoning": "Invalid JSON response from LLM",
        }


async def deepseek_chat(prompt: str):
    """
    Async DeepSeek chat with normalized response.
    Returns (text, raw_response) tuple.
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set.")
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        data = response.json()
        
        # Extract text from response
        text = ""
        if "choices" in data and len(data["choices"]) > 0:
            message = data["choices"][0].get("message", {})
            text = message.get("content", "")
        
        return text, data


def deepseek_chat_sync(prompt: str):
    """
    Synchronous wrapper for deepseek_chat.
    Returns (text, raw_response) tuple.
    """
    return asyncio.run(deepseek_chat(prompt))
