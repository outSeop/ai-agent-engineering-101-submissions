
def test(run, kit):
    from unittest.mock import patch
    from types import SimpleNamespace
    import httpx

    wallet = "0x" + "1" * 40
    public = {"round": 4, "wallet": wallet, "balance": "hidden-balance",
              "units": [{"sku": "G0026722f", "grade": "A", "unit": "private-unit",
                         "cert": "private-cert", "cost": "private-cost"}]}
    ctx = SimpleNamespace(name="outseop-r4", market="https://market.ourolabs.ai",
                          address=lambda _: wallet, token=lambda _: "mock-private-token")
    def fetch(url, *, headers, timeout, trust_env):
        assert url == "https://market.ourolabs.ai/api/inventory"
        assert headers == {"authorization": "Bearer mock-private-token"}
        return httpx.Response(200, json=public, request=httpx.Request("GET", url))
    with patch.object(httpx, "get", fetch):
        result = run({"op": "buy", "task_id": "fake-scope"}, ctx)
        assert result["state"] == "completed"
        assert "G0026722f" in result["reply"] and "A" in result["reply"]
        assert all(secret not in str(result) for secret in ("private", "hidden", wallet, "mock-private-token"))
        public.clear()
        assert "조회" in run({}, ctx)["reply"]
    return {"authorship": "OpenAI Codex GPT-6.2 Sol", "mock": "read-only market inventory and published policy"}
