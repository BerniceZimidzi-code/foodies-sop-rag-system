# OpenRouter APIs — Google: Gemma 4 31B (free) (google/gemma-4-31b-it)

Guide for calling every confirmed OpenRouter API that serves `google/gemma-4-31b-it`.

Model page: https://openrouter.ai/google/gemma-4-31b-it
Create an API key: https://openrouter.ai/settings/keys

## EU in-region routing

`google/gemma-4-31b-it` is not currently available through EU in-region routing.

Docs: https://openrouter.ai/docs/guides/features/in-region-routing

## Authentication

Send this header with every request:

- Authorization: Bearer $OPENROUTER_API_KEY

## Text / Chat Completions API

Generate text with `google/gemma-4-31b-it` through OpenRouter's Chat Completions API.

Docs: https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion

### Endpoint

POST https://openrouter.ai/api/v1/chat/completions

Headers:
- Content-Type: application/json

### Request fields (google/gemma-4-31b-it)

- model: string (required) — `"google/gemma-4-31b-it"`
- messages: array (required) — ordered conversation messages with `role` and `content`
- stream: boolean (optional) — return Server-Sent Events as tokens are generated
- max_tokens: optional — accepted by this model; see the API reference for its value shape
- reasoning: optional — accepted by this model; see the API reference for its value shape
- response_format: optional — accepted by this model; see the API reference for its value shape
- seed: optional — accepted by this model; see the API reference for its value shape
- temperature: optional — accepted by this model; see the API reference for its value shape
- tool_choice: optional — accepted by this model; see the API reference for its value shape
- tools: optional — accepted by this model; see the API reference for its value shape
- top_p: optional — accepted by this model; see the API reference for its value shape

The model-specific optional fields above come from this model's advertised capabilities.
`stream` and `provider` routing preferences are API controls accepted independently of that
model capability list.

### Response

Without `stream`, the response is a Chat Completions JSON object:

```json
{
  "id": "gen-abc123",
  "choices": [{ "message": { "role": "assistant", "content": "..." } }],
  "usage": { "prompt_tokens": 12, "completion_tokens": 24, "total_tokens": 36, "cost": 0.001 }
}
```

With `stream: true`, the response is `text/event-stream`: read each `data:` JSON chunk until
`data: [DONE]`. The final usage chunk carries token counts and cost when usage is requested.

### Examples

#### Chat completion

```bash
curl -X POST https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
  "model": "google/gemma-4-31b-it",
  "messages": [
    {
      "role": "user",
      "content": "What is the meaning of life?"
    }
  ]
}'
```

### Error differences

- 400 — malformed messages or a parameter this model does not support
- 502 — the upstream text generation failed

## Errors

Failures return `{"error": {"code": <number>, "message": <string>}}` with the HTTP status:

- 400 — malformed request or an unsupported parameter
- 401 — missing or invalid API key
- 402 — insufficient credits
- 403 — spend limit reached, key disabled, or access blocked
- 404 — unknown model or no provider can serve the request
- 429 — rate limited; retry with backoff
- 502 — the operation failed upstream; failed generations are not billed

---

Canonical version of this document: https://openrouter.ai/google/gemma-4-31b-it/llms.txt
