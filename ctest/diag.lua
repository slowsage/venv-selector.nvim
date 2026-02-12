vim.defer_fn(function()
  for _, d in ipairs(vim.diagnostic.get(0)) do
    local sev = vim.diagnostic.severity[d.severity]
    io.write(d.lnum .. ":" .. d.col .. " " .. sev .. ": " .. d.message .. "\n")
  end
  io.flush()
  vim.cmd("qa!")
end, 8000)
