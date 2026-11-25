"""Host transport for the fixed local official cli_model bridge."""
import httpx

CLI_ENDPOINT = "http://127.0.0.1:19001/v1"
CLI_READ_TIMEOUT = 315


def complete_cli(messages, max_tokens=4000, timeout=315):
    limit = min(CLI_READ_TIMEOUT, timeout)
    with httpx.Client(
        trust_env=False, follow_redirects=False,
        timeout=httpx.Timeout(limit, connect=min(4, limit)),
    ) as client:
        response = client.post(
            CLI_ENDPOINT + "/chat/completions",
            json={"model": "cli", "messages": messages, "max_tokens": max_tokens},
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("local CLI bridge did not return a model reply")
        return reply

