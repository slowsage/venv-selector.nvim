local M = {}
local log_file = nil

function M.init(path)
  if log_file then return end -- already initialized
  log_file = io.open(path, "w")
  if log_file then
    log_file:write("=== TRACE START " .. os.date() .. " ===\n")
    log_file:flush()
  end
end

function M.log(fmt, ...)
  local msg = string.format(fmt, ...)
  local line = os.date("[%H:%M:%S] ") .. msg .. "\n"
  if log_file then
    log_file:write(line)
    log_file:flush()
  end
  io.stderr:write("[TRACE] " .. msg .. "\n")
end

function M.close()
  if log_file then
    log_file:write("=== TRACE END ===\n")
    log_file:close()
    log_file = nil
  end
end

return M
