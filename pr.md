# fix: force-kill pull-diagnostic LSP clients on venv restart

## Symptom

After `:VenvSelect` switches Python venvs, the old LSP client's diagnostic
namespace still displays errors from the previous venv — e.g.
`Import "questionary" could not be resolved` — even though a fresh client is
running correctly against the new venv. The stale diagnostics persist until
Neovim is restarted.

Observable with:
```vim
:lua for n, id in pairs(vim.api.nvim_get_namespaces()) do if n:find("basedpyright") then print(id, n) end end
41  nvim.lsp.basedpyright.1.basedpyright    ← dead client, still holding stale errors
46  nvim.lsp.basedpyright.6                  ← new client, correct
```

## Root cause

Neovim's pull-diagnostic mechanism stores response handlers in
`rpc.message_callbacks`, keyed by request id. Each handler is captured as a
closure at send-time (`vim.lsp.client.Client:request()`); `on_diagnostic` runs
it when the response arrives, **without checking whether the client is
stopping**.

Graceful stop (`c:stop(false)`) sends the LSP `shutdown` request and waits for
the server process to exit. Inside that window:

1. Neovim's per-client pull-diagnostic poller fires another
   `textDocument/diagnostic` against the stopping client.
2. The server responds `ServerCancelled` (it's shutting down).
3. `on_diagnostic` in `runtime/lua/vim/lsp/diagnostic.lua:277` treats
   `ServerCancelled` as transient and **immediately retriggers**:
   ```lua
   if error ~= nil and error.code == protocol.ErrorCodes.ServerCancelled then
     if error.data == nil or error.data.retriggerRequest ~= false then
       client:request(ctx.method, ctx.params, nil, ctx.bufnr)
     end
     return
   end
   ```
4. The server, still running and still holding its pre-shutdown state, runs
   type analysis and responds with stale diagnostics.
5. The client finishes shutdown, `_on_exit` runs, `LspDetach` fires and clears
   the pull namespace.
6. The retriggered response from step 4 arrives. Its callback is still sitting
   in `rpc.message_callbacks`, the closure still holds the handler — it fires
   and writes the stale diagnostics back into the now-cleared namespace.

Step 5 cleans up; step 6 re-dirties the namespace. There is no way for the
cleanup in step 5 to race past the in-flight response in step 6 — they are on
independent timelines.

In practice only basedpyright exhibits this visibly. Ruff (Rust binary) exits
fast enough that by the time `on_diagnostic` calls `client:request()` for the
retrigger, the transport is already closing, and `rpc.encode_and_send` silently
drops the outbound write. Basedpyright runs on Node.js and stays alive long
enough for the retriggered request to be written, processed, and answered.

## Why force-kill fixes it

`c:stop(true)` calls `rpc.terminate()`, which closes the transport
**synchronously**. Pending entries in `rpc.message_callbacks` are abandoned —
there is no code path that iterates them and fires their callbacks on
transport close (confirmed at `runtime/lua/vim/lsp/rpc.lua:367`, where a
`-- TODO periodically check message_callbacks...` comment notes the absence of
any cleanup sweep).

The in-flight response handler simply never runs. No retrigger. No stale
write. `LspDetach`'s clear is the last thing to touch the namespace, and it
stays cleared.

This is the only mechanism in Neovim's LSP stack that atomically drops pending
response handlers. Every alternative (see below) leaves a window open because
the closures have already been captured by value and are held by the RPC
layer.

## Why only pull-diagnostic clients

Force-kill is scoped with `c:supports_method("textDocument/diagnostic")`.
Push-only clients (those relying on `textDocument/publishDiagnostics` from the
server) do not maintain a request loop, so they have no pending response
callbacks at shutdown time — graceful stop is sufficient and preferred, since
it gives the server a chance to flush state cleanly.

`supports_method()` is used rather than reading
`server_capabilities.diagnosticProvider` because servers commonly register
`textDocument/diagnostic` via dynamic `client/registerCapability` **after**
initialization, which leaves the static capabilities field nil.
`supports_method()` consults both static and dynamic registration, so it
catches both.

## Alternatives considered and rejected

- **Shadow `c.request` to block `textDocument/diagnostic`** (previously tried
  on `fix/mark-restarting`): blocks *new* outbound requests, does nothing
  about responses already dispatched and waiting in `message_callbacks`. The
  race survives.
- **Shadow `c.handlers["textDocument/diagnostic"]` with a no-op** (previously
  tried on `fix/disable_restart_handler`): `Client:request()` captures the
  handler by value into a closure at send-time. Mutating `c.handlers`
  afterwards has no effect on in-flight requests.
- **Call `vim.diagnostic.reset(ns, bufnr)` on the old namespace after the
  poll cycle detects `alive_count == 0`**: works, but requires tracking
  `(client_name, client_id)` pairs through the gate's polling state machine,
  matching namespaces by prefix (`nvim.lsp.<name>.<id>[.<provider>]`), and
  handling snapshot lifecycle across gen bumps, force-stop-failed aborts, and
  rapid switch sequences. ~45 lines of new state machinery for a problem that
  force-kill solves in ~10.

## The change

```lua
-- lsp_gate.lua, inside M.request(), immediately before stop_all_by_key:
local force = false
for _, c in ipairs(clients_for_key(key)) do
  if type(c.supports_method) == "function" and c:supports_method("textDocument/diagnostic") then
    force = true
    break
  end
end
stop_all_by_key(key, force)
```

10 lines including the comment. The gate's existing `MAX_TRIES` escalation
still provides a force-kill safety net if a push-only client ever fails to
exit gracefully within `MAX_TRIES * POLL_INTERVAL_MS`.
