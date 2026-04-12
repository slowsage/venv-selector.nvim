# fix: suppress pull-diagnostic handler on venv restart

## Problem

After venv activation, pull-diagnostic LSP clients (those advertising
`textDocument/diagnostic`) leave stale diagnostics in Neovim's diagnostic list
even after the new client starts with the correct `pythonPath`.

## Root cause

Graceful shutdown (`c:stop(false)`) sends a `shutdown` request and waits.
During that window, Neovim's pull-diagnostic poller fires another
`textDocument/diagnostic` request. The server responds `ServerCancelled`
(it is shutting down). Neovim's `on_diagnostic` handler treats `ServerCancelled`
as transient and **immediately re-issues the request** without checking whether
the client is stopping:

```
-- runtime/lua/vim/lsp/diagnostic.lua:277
if error ~= nil and error.code == protocol.ErrorCodes.ServerCancelled then
  if error.data == nil or error.data.retriggerRequest ~= false then
    client:request(ctx.method, ctx.params, nil, ctx.bufnr)
  end
  return
end
```

`LspDetach` fires and clears the pull namespace. The retriggered response
arrives after `LspDetach` and re-populates it with stale errors.

## Fix

Before stopping, override `client.handlers["textDocument/diagnostic"]` to a
no-op on each pull-diagnostic client. `Client:request()` resolves the response
handler via `Client:_resolve_handler()` (client.lua:656), which checks
`self.handlers` first. Any in-flight or retriggered `textDocument/diagnostic`
response calls the no-op and returns without retriggering. Graceful shutdown
proceeds normally. The override is on the client being discarded so there is no
lasting side-effect.

```lua
-- gate.request() in lsp_gate.lua
for _, c in ipairs(clients_for_key(key)) do
  if type(c.supports_method) == "function" and c:supports_method("textDocument/diagnostic") then
    c.handlers = c.handlers or {}
    c.handlers["textDocument/diagnostic"] = function() end
  end
end
stop_all_by_key(key, false)
```

`supports_method()` is used rather than `server_capabilities.diagnosticProvider`
because servers can register `textDocument/diagnostic` via dynamic
`client/registerCapability` after initialization; the static capabilities field
is nil for these servers.

## Why only pull-diagnostic clients

Push clients (`textDocument/publishDiagnostics`) have no active request loop.
Graceful stop → server stops sending → `LspDetach` clears namespace. No
in-flight request, no `ServerCancelled`, no retrigger.

Pull clients have a per-client polling loop maintained by Neovim
(`client_pull_namespaces` vs `client_push_namespaces` in `diagnostic.lua:189,192`).

## Affected servers

Any server registering `textDocument/diagnostic` support. Ruff always uses pull
diagnostics (`diagnostic_provider` in static `serverCapabilities`, no
`publishDiagnostics`). Basedpyright likewise.

In practice the stale-namespace race only manifests with basedpyright. Ruff
(Rust binary) exits fast enough that by the time `on_diagnostic` calls
`client:request()` for the retrigger, `rpc.encode_and_send` finds
`transport:is_closing() == true` and silently drops the request — the retrigger
is never written to the channel. Basedpyright (Node.js) stays alive long enough
that `is_closing()` is still false when the retrigger fires, so the request is
sent, basedpyright runs type analysis and responds, and that response re-populates
the namespace that `LspDetach` already cleared.
