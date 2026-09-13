# llm.py -- TRANSPORT ONLY. Model se baat karna, bas.
import os
import time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama")


def _build_client() -> tuple[OpenAI, str]:
    """Return (client, model_name) for the provider chosen in .env."""
    if PROVIDER == "ollama":
        return (
            OpenAI(
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                api_key="ollama",
            ),
            os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
        )

    if PROVIDER == "openai":
        return (OpenAI(api_key=os.getenv("OPENAI_API_KEY")), "gpt-4o-mini")

    raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER}")


client, MODEL = _build_client()


def chat(
    messages: list[dict],
    temperature: float = 0.7,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,        # <-- 1. NAYA PARAMETER
) -> dict:
    """Send a conversation to the LLM. Returns reply + raw message + usage."""
    started = time.perf_counter()

    kwargs = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        if tool_choice:                            # <-- 2. NAYA (tools ke ANDAR)
            kwargs["tool_choice"] = tool_choice

    response = client.chat.completions.create(**kwargs)
    message = response.choices[0].message

    return {
        "reply": message.content,
        "message": message,              # raw -- tool_calls isme hote hain
        "tool_calls": message.tool_calls,
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model": MODEL,
    }


if __name__ == "__main__":
    r = chat([{"role": "user", "content": "Reply with exactly: OK"}])
    print(r["reply"], "|", r["latency_ms"], "ms")