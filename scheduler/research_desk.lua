-- Overnight research desk scheduler: OPTIONAL example for macOS with Hammerspoon (https://www.hammerspoon.org).
-- Any scheduler works (cron, launchd, systemd timers); this one exists because launchd user agents can't read some
-- external volumes, while Hammerspoon can. It changes no sleep or energy settings and needs no sudo.
-- Turn on: add one line to your Hammerspoon init.lua, then reload Hammerspoon:
--     pcall(dofile, "/path/to/overnight-research-desk-public/scheduler/research_desk.lua")
-- Turn off: delete that line and reload.
-- Times are local time. Runs Mon-Fri mornings (covers Sun-Thu nights before each trading day).
-- If the Mac is asleep at the scheduled minute the run does NOT happen; a missed run is caught up once on wake if it is
-- still before 7:00 AM. Put REVIEW_CMD and any DESK_* settings in the repo's .env or in the environment below.
local M = {}
-- Path of this repo: taken from this file's own location (scheduler/research_desk.lua).
local DESK = (debug.getinfo(1, "S").source:match("^@(.*)/scheduler/[^/]*$")) or (os.getenv("HOME") .. "/overnight-research-desk-public")
local LOG = DESK .. "/outputs/scheduler.log"
local JOBS = {
  { id = "collector", at = "01:00", script = DESK .. "/run/run-collector.sh" },
  { id = "review",    at = "04:30", script = DESK .. "/run/run-review.sh" },
}
local CATCHUP_UNTIL_HOUR = 7

local function log(msg)
  local f = io.open(LOG, "a")
  if f then f:write(os.date("%Y-%m-%d %H:%M:%S ") .. msg .. "\n"); f:close() end
end
local function weekday() local w = tonumber(os.date("%w")); return w >= 1 and w <= 5 end
local lastRun = {}         -- id -> "YYYY-MM-DD"
local running = {}

local function run(job, why)
  local today = os.date("%Y-%m-%d")
  if not weekday() then return end
  if lastRun[job.id] == today then return end
  if running[job.id] then log(job.id .. ": still running, skip (" .. why .. ")"); return end
  lastRun[job.id] = today; running[job.id] = true
  log(job.id .. ": start (" .. why .. ")")
  local t = hs.task.new("/bin/bash", function(code, out, err)
    running[job.id] = nil
    log(job.id .. ": exit " .. tostring(code))
  end, { "-c", job.script .. " " .. today })
  t:setEnvironment({ PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", HOME = os.getenv("HOME") })
  if not t:start() then running[job.id] = nil; log(job.id .. ": FAILED to start") end
  M.tasks = M.tasks or {}; M.tasks[job.id] = t
end

local function minutes(hhmm) local h, m = hhmm:match("(%d+):(%d+)"); return tonumber(h) * 60 + tonumber(m) end
local function catchUp(why)
  local now = tonumber(os.date("%H")) * 60 + tonumber(os.date("%M"))
  if now >= CATCHUP_UNTIL_HOUR * 60 then return end
  -- collector first; the review waits for it (review only starts once the collector is not running)
  for _, job in ipairs(JOBS) do
    if now >= minutes(job.at) and lastRun[job.id] ~= os.date("%Y-%m-%d") then
      if job.id == "review" and running["collector"] then
        hs.timer.doAfter(300, function() catchUp("retry after collector") end); return
      end
      run(job, why)
      if job.id == "collector" then hs.timer.doAfter(600, function() catchUp("follow-up") end); return end
    end
  end
end

function M.start()
  M.timers = {}
  for _, job in ipairs(JOBS) do
    table.insert(M.timers, hs.timer.doAt(job.at, "1d", function() run(job, "scheduled " .. job.at) end, true))
  end
  M.wake = hs.caffeinate.watcher.new(function(ev)
    if ev == hs.caffeinate.watcher.systemDidWake then hs.timer.doAfter(60, function() catchUp("wake catch-up") end) end
  end)
  M.wake:start()
  log("scheduler loaded: collector 01:00, review 04:30, Mon-Fri")
end

-- Report what is scheduled (for `hs -c 'researchDesk.status()'`): next fire time of each job, local time.
function M.status()
  local out = {}
  for i, job in ipairs(JOBS) do
    local t = M.timers and M.timers[i]
    local nxt = t and t:running() and os.date("%a %Y-%m-%d %H:%M", math.ceil(os.time() + t:nextTrigger())) or "not running"
    table.insert(out, job.id .. " next " .. nxt .. " (runs only Mon-Fri)")
  end
  return table.concat(out, "; ")
end

if _G.researchDesk and _G.researchDesk.timers then        -- reloads replace the old timers, never double them
  for _, t in ipairs(_G.researchDesk.timers) do t:stop() end
  if _G.researchDesk.wake then _G.researchDesk.wake:stop() end
end
M.start()
_G.researchDesk = M      -- global reference keeps the timers alive (unreferenced hs.timer objects get garbage-collected)
log("next: " .. M.status())
return M
