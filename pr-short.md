# fix: force-kill pull-diagnostic LSP clients on venv restart

## Symptom

After `:VenvSelect`, the old LSP client's diagnostic namespace still shows
errors from the previous venv (e.g. `Import "questionary" could not be
resolved`). The new client is running correctly against the new venv, but the
old namespace is stuck until Neovim is restarted.

## Root cause

Graceful stop (`c:stop(false)`) sends `shutdown` and waits for the server to
exit. Inside that window:

1. Neovim's pull-diagnostic poller fires another `textDocument/diagnostic`.
2. Server responds `ServerCancelled`; `on_diagnostic` retriggers the request
   unconditionally (no `is_stopped` guard).
3. Server answers the retrigger normally — it's still running and still holds
   its old state.
4. `LspDetach` fires and clears the pull namespace.
5. The retriggered response lands **after** step 4. Its callback is still in
   `rpc.message_callbacks` as a closure captured at send-time, so it runs and
   re-populates the namespace with stale errors.

Only basedpyright exhibits this visibly — Node.js stays alive long enough for
the retrigger to round-trip. Ruff (Rust) exits before the retrigger can be
written; the race window is effectively zero for it.

## Fix

Force-kill (`c:stop(true)`) calls `rpc.terminate()`, which closes the transport
synchronously. Pending entries in `rpc.message_callbacks` are abandoned — no
code path iterates them on transport close. The in-flight closure never runs,
no stale write occurs, and `LspDetach`'s clear is the last word on the
namespace.

Scoped to clients advertising `textDocument/diagnostic` via
`c:supports_method()` (which covers dynamic registration). Push-only clients
still stop gracefully.

## Alternatives rejected

- Shadowing `c.request` / `c.handlers`: response handlers are captured by value
  into closures at send-time, so mutating them later does not affect in-flight
  requests.
- Explicit `vim.diagnostic.reset` after `LspDetach`: ~45 lines of state
  machinery to track `(client_name, client_id)` namespace identity through the
  gate's polling state machine. Force-kill solves the same problem in ~10
  lines.
