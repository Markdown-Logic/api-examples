# REST examples and MCP connections

The numbered programs in this repository call REST. They are not MCP tool names or MCP client SDKs. Choose the [MCP help guide](https://markdownlogic.com/help/en/connect-an-ai-assistant) to connect an assistant.

| Connection | Address | Authority |
| --- | --- | --- |
| Public Markdown conversion | `https://markdownlogic.com/mcp` | Supplied complete Markdown only; no private project access |
| Private project work | `https://mcp.markdownlogic.com` | Browser OAuth, granted scopes, team membership, role and plan |

For private work, ask the client to list/read authorized projects before requesting an edit. Keep the stable document identity and observed revision when using advertised write tools. Follow the live tool schema, preserve source and stop to reconcile conflicts or uncertain writes. A REST endpoint or CLI command is not evidence that a corresponding MCP tool exists.

Public conversion can return embedded file bytes; a resource URI is not automatically a hosted download URL. Use a client capable of saving those bytes. Follow the selected connection's live limits and refusals; this repository does not run conversions as a discovery test.

The public [Cursor package](https://github.com/Markdown-Logic/mcp-plugin-cursor) includes local-review installation instructions and notices. Authenticated acceptance and marketplace listing remain pending; do not imply a completed listing from package/CI checks.

The 2026-11-03 read-only public `initialize` probe received HTTP403 and was not retried or bypassed. No tool invocation, conversion, consent or private access was attempted. These REST fixture tests therefore establish no end-to-end MCP client acceptance.
