# AG-UI backend

The AG-UI backend connects Ebi Agent Chat Relay to a remote agent that implements the
[Agent–User Interaction Protocol](https://docs.ag-ui.com/). It keeps Discord and Teams as the
conversation surfaces while replacing the local Claude/Codex CLI process with an HTTP/SSE agent.

## Install and configure

Install the optional HTTP dependency:

```bash
pip install 'claude-code-discord-bridge[agui]'
```

Configure the exact run endpoint and, when required, its bearer token:

```dotenv
CCDB_AGUI_URL=https://agent.example.com/run
CCDB_AGUI_TOKEN=replace-with-upstream-token
```

Then select it globally with `CCDB_BACKEND=agui` or at runtime with `/backend agui`. A thread-scoped
selection affects only that conversation.

## Wire behavior

For every turn, ccdb sends the standard `RunAgentInput` JSON shape with:

- a stable `threadId` (the remote ID returned by `RUN_STARTED` is persisted for later turns);
- a fresh `runId`;
- the current user prompt and any image attachments;
- empty `state`, `tools`, `context`, and `forwardedProps` values.

The endpoint must return `text/event-stream` containing JSON AG-UI events. The backend currently
maps run lifecycle, streamed assistant text, reasoning text, tool calls, and tool results into
ccdb's frontend-neutral `StreamEvent` model.

The remote endpoint must retain conversation state by `threadId`. This first interoperability
layer sends the current user turn rather than replaying a full local transcript on every request.

## Deliberate limits

This version fails explicitly instead of pretending to support protocol features it cannot yet
resume safely:

- interrupt/resume outcomes (human-in-the-loop);
- client-provided AG-UI tools;
- protobuf event streams;
- AG-UI state and activity rendering.

An interrupt outcome is reported as an error to the conversation. A future durable interaction
store can add restart-safe resume support without changing the transport contract.

## Security boundary

Treat the endpoint as an AI backend with access to every prompt sent through a selected thread.

- Prefer HTTPS. HTTP is accepted for local development and trusted private networks.
- Credentials in the URL are rejected; use `CCDB_AGUI_TOKEN`.
- HTTP redirects are not followed, preventing bearer-token forwarding to another endpoint.
- `CCDB_AGUI_TOKEN` is removed from Claude and Codex child-process environments.
- Non-success response bodies are not echoed into Discord or Teams.
- Each SSE event is bounded to 1 MiB and must be a JSON object.
- The endpoint URL and token are omitted from status labels and logs.

Use a dedicated, least-privilege token and do not route customer or regulated data to an endpoint
until its data handling boundary has been approved.
