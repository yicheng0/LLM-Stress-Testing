"""Local mock endpoints for safe vendor billing self-test checks."""
from __future__ import annotations

import argparse
import json
from aiohttp import web


def _usage(request: web.Request) -> dict[str, int]:
    input_tokens = int(request.headers.get("X-Mock-Input-Tokens", "128"))
    output_tokens = int(request.headers.get("X-Mock-Output-Tokens", "16"))
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


async def completions(request: web.Request) -> web.StreamResponse:
    payload = await request.json()
    usage = _usage(request)
    if request.query.get("missing_usage") == "1":
        usage = None
    body = {
        "id": "mock-response",
        "object": "chat.completion",
        "model": payload.get("model", "mock-model"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
    }
    if usage is not None:
        body["usage"] = usage
    if payload.get("stream"):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n')
        await response.write(f"data: {json.dumps({'usage': usage or {}, 'choices': []})}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response
    return web.json_response(body)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/v1/chat/completions", completions)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Local mock OpenAI-compatible vendor API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    web.run_app(build_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
