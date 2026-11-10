"""Calls to the local Ollama server and the chat tool loop. Owner: Ming."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from config import MAX_WEB_SEARCH_CALLS, MODEL, OLLAMA_CHAT_TIMEOUT, OLLAMA_CHAT_URL, OLLAMA_WEB_SEARCH_URL

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current facts or information not contained in the uploaded documents.",
        "parameters": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "A concise web search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return, from 1 to 5.",
                },
            },
        },
    },
}


class OllamaError(Exception):
    """An Ollama request failed or returned an invalid response."""


def ollama_post(url, payload, timeout=120):
    body = json.dumps(payload).encode("utf-8")
    ollama_request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(ollama_request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace").strip()
        raise OllamaError(f"Ollama returned HTTP {error.code}: {details or error.reason}") from error
    except (URLError, TimeoutError, OSError) as error:
        host = urlsplit(url).netloc
        raise OllamaError(f"Could not reach {host}: {error}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OllamaError("Ollama returned an invalid response.") from error


def web_search(query, max_results=5):
    """Call Ollama's hosted web search without persisting or exposing its key."""
    api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if not api_key:
        raise OllamaError("Web search is unavailable. Set OLLAMA_API_KEY in the environment and restart the app.")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("The web search query must not be empty.")
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        max_results = 5
    max_results = max(1, min(max_results, 5))

    body = json.dumps({"query": query.strip()[:500], "max_results": max_results}).encode("utf-8")
    search_request = Request(
        OLLAMA_WEB_SEARCH_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(search_request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace").strip()
        raise OllamaError(f"Ollama web search returned HTTP {error.code}: {details or error.reason}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise OllamaError(f"Could not reach Ollama web search at ollama.com: {error}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OllamaError("Ollama web search returned an invalid response.") from error

    results = result.get("results") if isinstance(result, dict) else None
    if not isinstance(results, list):
        raise OllamaError("Ollama web search returned an invalid result list.")
    compact_results = []
    for item in results[:max_results]:
        if isinstance(item, dict):
            compact_results.append({
                "title": str(item.get("title", ""))[:300],
                "url": str(item.get("url", ""))[:1000],
                "content": str(item.get("content", ""))[:2500],
            })
    return compact_results


def run_chat_with_tools(messages):
    """Let the model search at most four times, then request its final answer."""
    search_calls = 0
    for _round in range(MAX_WEB_SEARCH_CALLS):
        result = ollama_post(
            OLLAMA_CHAT_URL,
            {"model": MODEL, "messages": messages, "tools": [WEB_SEARCH_TOOL], "stream": False},
            timeout=OLLAMA_CHAT_TIMEOUT,
        )
        assistant_message = result.get("message") if isinstance(result, dict) else None
        if not isinstance(assistant_message, dict):
            raise OllamaError("Ollama returned an invalid chat response.")
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            return assistant_message

        # Keep the assistant's tool-call message in the history so Ollama can
        # associate each tool result with the request that produced it.
        messages.append(assistant_message)
        for call in tool_calls:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = function.get("name")
            arguments = function.get("arguments", {})
            if name != "web_search":
                tool_result = {"error": "Unsupported tool."}
            elif search_calls >= MAX_WEB_SEARCH_CALLS:
                tool_result = {"error": "Search limit reached. Give the best final answer from the results so far."}
            else:
                search_calls += 1
                try:
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be an object.")
                    tool_result = {"results": web_search(**arguments)}
                except (OllamaError, TypeError, ValueError) as error:
                    tool_result = {"error": str(error)}
            messages.append({
                "role": "tool",
                "tool_name": name or "web_search",
                "content": json.dumps(tool_result, ensure_ascii=False),
            })

    # One last call has no tools, guaranteeing a final response even if the
    # model tries to search again after reaching the four-call cap.
    messages.append({
        "role": "system",
        "content": "Search limit reached. Answer now using the available document and search context.",
    })
    final_result = ollama_post(
        OLLAMA_CHAT_URL,
        {"model": MODEL, "messages": messages, "stream": False},
        timeout=OLLAMA_CHAT_TIMEOUT,
    )
    final_message = final_result.get("message") if isinstance(final_result, dict) else None
    if not isinstance(final_message, dict):
        raise OllamaError("Ollama returned an invalid final response.")
    return final_message
