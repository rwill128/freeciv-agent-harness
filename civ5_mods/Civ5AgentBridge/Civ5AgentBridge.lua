local STATE_PREFIX = "CIV5_AGENT_STATE\t"
local COMMAND_PREFIX = "CIV5_AGENT_COMMAND\t"

local function json_escape(value)
  value = tostring(value or "")
  value = string.gsub(value, "\\", "\\\\")
  value = string.gsub(value, "\"", "\\\"")
  value = string.gsub(value, "\b", "\\b")
  value = string.gsub(value, "\f", "\\f")
  value = string.gsub(value, "\n", "\\n")
  value = string.gsub(value, "\r", "\\r")
  value = string.gsub(value, "\t", "\\t")
  return value
end

local function json_encode(value)
  local value_type = type(value)
  if value_type == "nil" then
    return "null"
  end
  if value_type == "boolean" then
    return value and "true" or "false"
  end
  if value_type == "number" then
    return tostring(value)
  end
  if value_type == "string" then
    return "\"" .. json_escape(value) .. "\""
  end
  if value_type == "table" then
    local is_array = true
    local max_index = 0
    for key, _ in pairs(value) do
      if type(key) ~= "number" or key < 1 or math.floor(key) ~= key then
        is_array = false
        break
      end
      if key > max_index then
        max_index = key
      end
    end
    local parts = {}
    if is_array then
      for index = 1, max_index do
        table.insert(parts, json_encode(value[index]))
      end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    for key, child in pairs(value) do
      table.insert(parts, json_encode(tostring(key)) .. ":" .. json_encode(child))
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return json_encode(tostring(value))
end

local function text(value)
  if value == nil then
    return nil
  end
  return Locale.ConvertTextKey(value)
end

local function safe_call(callback, fallback)
  local ok, result = pcall(callback)
  if ok then
    return result
  end
  return fallback
end

local function unit_type_name(unit_type)
  local info = GameInfo.Units[unit_type]
  if info == nil then
    return nil
  end
  return info.Type
end

local function unit_description(unit_type)
  local info = GameInfo.Units[unit_type]
  if info == nil then
    return nil
  end
  return text(info.Description) or info.Type
end

local function terrain_type_name(terrain_type)
  local info = GameInfo.Terrains[terrain_type]
  if info == nil then
    return nil
  end
  return info.Type
end

local function feature_type_name(feature_type)
  if feature_type == nil or feature_type < 0 then
    return nil
  end
  local info = GameInfo.Features[feature_type]
  if info == nil then
    return nil
  end
  return info.Type
end

local function resource_type_name(resource_type)
  if resource_type == nil or resource_type < 0 then
    return nil
  end
  local info = GameInfo.Resources[resource_type]
  if info == nil then
    return nil
  end
  return info.Type
end

local function collect_units(player)
  local units = {}
  for unit in player:Units() do
    local unit_type = unit:GetUnitType()
    table.insert(units, {
      id = unit:GetID(),
      type = unit_type,
      type_name = unit_type_name(unit_type),
      name = unit_description(unit_type),
      x = unit:GetX(),
      y = unit:GetY(),
      damage = safe_call(function() return unit:GetDamage() end, nil),
      moves = safe_call(function() return unit:MovesLeft() end, nil),
      combat_limit = safe_call(function() return unit:GetBaseCombatStrength() end, nil),
      ranged_combat = safe_call(function() return unit:GetBaseRangedCombatStrength() end, nil),
      domain = safe_call(function() return unit:GetDomainType() end, nil),
      is_embarked = safe_call(function() return unit:IsEmbarked() end, false),
      can_found = safe_call(function() return unit:CanFound(unit:GetPlot()) end, false),
      is_trade = safe_call(function() return unit:IsTrade() end, false),
    })
  end
  return units
end

local function collect_cities(player)
  local cities = {}
  for city in player:Cities() do
    table.insert(cities, {
      id = city:GetID(),
      name = city:GetName(),
      x = city:GetX(),
      y = city:GetY(),
      population = safe_call(function() return city:GetPopulation() end, nil),
      damage = safe_call(function() return city:GetDamage() end, nil),
      food = safe_call(function() return city:GetFood() end, nil),
      production = safe_call(function() return city:GetProduction() end, nil),
      production_name = safe_call(function() return city:GetProductionName() end, nil),
    })
  end
  return cities
end

local function collect_visible_plots(team_id)
  local plots = {}
  local plot_count = Map.GetNumPlots()
  for index = 0, plot_count - 1 do
    local plot = Map.GetPlotByIndex(index)
    if plot ~= nil and plot:IsRevealed(team_id, false) then
      table.insert(plots, {
        index = index,
        x = plot:GetX(),
        y = plot:GetY(),
        terrain = terrain_type_name(plot:GetTerrainType()),
        feature = feature_type_name(plot:GetFeatureType()),
        resource = resource_type_name(plot:GetResourceType(team_id)),
        owner = plot:GetOwner(),
        is_city = plot:IsCity(),
        is_water = plot:IsWater(),
        is_hills = plot:IsHills(),
        is_mountain = plot:IsMountain(),
      })
    end
  end
  return plots
end

local function build_state()
  local active_player_id = Game.GetActivePlayer()
  local player = Players[active_player_id]
  if player == nil then
    return {
      schema = "civ5-agent-state-v0",
      error = "no active player",
      game = {
        turn = Game.GetGameTurn(),
      },
    }
  end
  local team_id = player:GetTeam()
  return {
    schema = "civ5-agent-state-v0",
    game = {
      turn = Game.GetGameTurn(),
      year = Game.GetGameTurnYear(),
      active_player_id = active_player_id,
      active_team_id = team_id,
    },
    player = {
      id = active_player_id,
      name = player:GetName(),
      leader_name = player:GetName(),
      civilization_short_description = safe_call(function() return text(player:GetCivilizationShortDescription()) end, nil),
      civilization_description = safe_call(function() return text(player:GetCivilizationDescription()) end, nil),
      civilization_type = safe_call(function() return player:GetCivilizationType() end, nil),
      team = team_id,
      gold = safe_call(function() return player:GetGold() end, nil),
      happiness = safe_call(function() return player:GetExcessHappiness() end, nil),
      current_research = safe_call(function() return player:GetCurrentResearch() end, nil),
      science = safe_call(function() return player:GetScience() end, nil),
      culture = safe_call(function() return player:GetJONSCulture() end, nil),
      is_human = safe_call(function() return player:IsHuman() end, nil),
    },
    cities = collect_cities(player),
    units = collect_units(player),
    visible_plots = collect_visible_plots(team_id),
  }
end

local function emit_state(reason)
  local state = build_state()
  state.reason = reason
  print(STATE_PREFIX .. json_encode(state))
end

local function emit_command_result(command, ok, details)
  local payload = details or {}
  payload.schema = "civ5-agent-command-result-v0"
  payload.command = command
  payload.ok = ok
  payload.turn = Game.GetGameTurn()
  print(COMMAND_PREFIX .. json_encode(payload))
end

function Civ5AgentBridge_DumpState()
  emit_state("manual")
end

function Civ5AgentBridge_EndTurn()
  emit_command_result("end_turn", false, {
    error = "end_turn command path is not validated yet on this macOS build",
  })
end

print("CIV5_AGENT_BRIDGE_READY")
emit_state("load")

Events.ActivePlayerTurnStart.Add(function()
  emit_state("active_player_turn_start")
end)

Events.SerialEventGameDataDirty.Add(function()
  emit_state("game_data_dirty")
end)
