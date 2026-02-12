vim.defer_fn(function()
  local clients = vim.lsp.get_clients({ bufnr = 0 })
  if #clients == 0 then
    io.write("No LSP clients attached\n")
  else
    for _, client in ipairs(clients) do
      io.write("LSP: " .. client.name .. "\n")
      local settings = client.config.settings or {}
      local python_settings = settings.python or {}
      io.write("  pythonPath: " .. tostring(python_settings.pythonPath or "nil") .. "\n")
      io.write("  venvPath: " .. tostring(python_settings.venvPath or "nil") .. "\n")
      io.write("  venv: " .. tostring(python_settings.venv or "nil") .. "\n")
      local cmd_env = client.config.cmd_env or {}
      io.write("  VIRTUAL_ENV: " .. tostring(cmd_env.VIRTUAL_ENV or "nil") .. "\n")
    end
  end
  io.flush()
  vim.cmd("qa!")
end, 8000)
