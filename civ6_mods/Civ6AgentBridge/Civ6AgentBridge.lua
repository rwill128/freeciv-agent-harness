-- Civ6 Agent Bridge
--
-- MVP purpose:
--   1. expose ExposedMembers.Civ6AgentBridge.DumpState()
--   2. print one framed JSON state snapshot to Lua.log
--   3. automatically dump state around turn/local-player changes
--   4. leave command hooks in one place for validation

local Bridge = {}
local STATE_PREFIX = "CIV6_AGENT_STATE\t"
local COMMAND_PREFIX = "CIV6_AGENT_COMMAND\t"
local STATUS_PREFIX = "CIV6_AGENT_STATUS\t"
local g_last_active_player = nil

local function safe_call(fn, fallback)
  local ok, value = pcall(fn)
  if ok then
    return value
  end
  return fallback
end

local function json_escape(value)
  value = tostring(value or "")
  value = value:gsub("\\", "\\\\")
  value = value:gsub("\"", "\\\"")
  value = value:gsub("\n", "\\n")
  value = value:gsub("\r", "\\r")
  value = value:gsub("\t", "\\t")
  return value
end

local function is_array(value)
  if type(value) ~= "table" then
    return false
  end
  local max_index = 0
  local count = 0
  for key, _ in pairs(value) do
    if type(key) ~= "number" then
      return false
    end
    if key > max_index then
      max_index = key
    end
    count = count + 1
  end
  return max_index == count
end

local function encode_json(value)
  local value_type = type(value)
  if value == nil then
    return "null"
  elseif value_type == "boolean" then
    return value and "true" or "false"
  elseif value_type == "number" then
    return tostring(value)
  elseif value_type == "string" then
    return "\"" .. json_escape(value) .. "\""
  elseif value_type == "table" then
    local parts = {}
    if is_array(value) then
      for index = 1, #value do
        table.insert(parts, encode_json(value[index]))
      end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    for key, item in pairs(value) do
      table.insert(parts, "\"" .. json_escape(key) .. "\":" .. encode_json(item))
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return "null"
end

local function valid_player_id(player_id)
  return player_id ~= nil and type(player_id) == "number" and player_id >= 0 and Players[player_id] ~= nil
end

local function command_result(command_name, ok, fields)
  fields = fields or {}
  fields.schema = "civ6-agent-command-result-v0"
  fields.command = command_name
  fields.ok = ok
  fields.turn = safe_call(function() return Game.GetCurrentGameTurn() end, nil)
  print(COMMAND_PREFIX .. encode_json(fields))
  if ok then
    Bridge.DumpStateForEvent("AfterCommand:" .. tostring(command_name))
  end
  return fields
end

local function type_name(table_ref, type_id)
  if table_ref == nil or type_id == nil or type_id < 0 then
    return nil
  end
  local row = table_ref[type_id]
  if row == nil then
    return tostring(type_id)
  end
  return row.UnitType or row.TechnologyType or row.CivicType or row.BuildingType
    or row.DistrictType or row.ImprovementType or row.ResourceType
    or row.TerrainType or row.FeatureType or row.LeaderType
    or row.CivilizationType or tostring(type_id)
end

local function active_player_id()
  local local_player = safe_call(function() return Game.GetLocalPlayer() end, -1)
  if valid_player_id(local_player) then
    return local_player
  end
  local local_observer = safe_call(function() return Game.GetLocalObserver() end, -1)
  if valid_player_id(local_observer) then
    return local_observer
  end
  if valid_player_id(g_last_active_player) then
    return g_last_active_player
  end
  return -1
end

local function get_unit(unit_id)
  local player_id = active_player_id()
  local unit = safe_call(function() return UnitManager.GetUnit(player_id, unit_id) end, nil)
  if unit ~= nil then
    return unit
  end
  local player = Players[player_id]
  local player_units = player and safe_call(function() return player:GetUnits() end, nil) or nil
  if player_units ~= nil and player_units.Members ~= nil then
    for _, candidate in player_units:Members() do
      if safe_call(function() return candidate:GetID() end, nil) == unit_id then
        return candidate
      end
    end
  end
  return nil
end

local function get_city(city_id)
  local player_id = active_player_id()
  return safe_call(function() return CityManager.GetCity(player_id, city_id) end, nil)
end

local function game_info_row(table_ref, type_or_id)
  if table_ref == nil or type_or_id == nil then
    return nil
  end
  local direct = safe_call(function() return table_ref[type_or_id] end, nil)
  if direct ~= nil then
    return direct
  end
  if type(type_or_id) == "string" then
    local upper = string.upper(type_or_id)
    direct = safe_call(function() return table_ref[upper] end, nil)
    if direct ~= nil then
      return direct
    end
  end
  return nil
end

local function apply_production_parameter(parameters, production_type, production_kind)
  local kind = production_kind and string.lower(tostring(production_kind)) or nil
  local target = tostring(production_type)
  local unit = (kind == nil or kind == "unit") and game_info_row(GameInfo.Units, target) or nil
  if unit ~= nil then
    parameters[CityOperationTypes.PARAM_UNIT_TYPE] = unit.Hash
    return "unit", unit.UnitType, unit.Hash
  end
  local building = (kind == nil or kind == "building") and game_info_row(GameInfo.Buildings, target) or nil
  if building ~= nil then
    parameters[CityOperationTypes.PARAM_BUILDING_TYPE] = building.Hash
    return "building", building.BuildingType, building.Hash
  end
  local district = (kind == nil or kind == "district") and game_info_row(GameInfo.Districts, target) or nil
  if district ~= nil then
    parameters[CityOperationTypes.PARAM_DISTRICT_TYPE] = district.Hash
    return "district", district.DistrictType, district.Hash
  end
  local project = (kind == nil or kind == "project") and game_info_row(GameInfo.Projects, target) or nil
  if project ~= nil then
    parameters[CityOperationTypes.PARAM_PROJECT_TYPE] = project.Hash
    return "project", project.ProjectType, project.Hash
  end
  return nil, nil, nil
end

local function player_summary(player_id)
  local player = Players[player_id]
  if player == nil then
    return { id = player_id }
  end
  local config = PlayerConfigurations and PlayerConfigurations[player_id] or nil
  return {
    id = player_id,
    name = safe_call(function() return config:GetPlayerName() end, nil),
    leader_type = safe_call(function() return config:GetLeaderTypeName() end, nil),
    civilization_type = safe_call(function() return config:GetCivilizationTypeName() end, nil),
    is_human = safe_call(function() return player:IsHuman() end, nil)
  }
end

local function unit_summary(unit)
  local unit_type = safe_call(function() return unit:GetType() end, -1)
  return {
    id = safe_call(function() return unit:GetID() end, nil),
    type_id = unit_type,
    type = type_name(GameInfo.Units, unit_type),
    x = safe_call(function() return unit:GetX() end, nil),
    y = safe_call(function() return unit:GetY() end, nil),
    moves_remaining = safe_call(function() return unit:GetMovesRemaining() end, nil),
    damage = safe_call(function() return unit:GetDamage() end, nil),
    formation_class = safe_call(function() return unit:GetFormationClass() end, nil)
  }
end

local function city_summary(city)
  return {
    id = safe_call(function() return city:GetID() end, nil),
    name = safe_call(function() return city:GetName() end, nil),
    x = safe_call(function() return city:GetX() end, nil),
    y = safe_call(function() return city:GetY() end, nil),
    population = safe_call(function() return city:GetPopulation() end, nil)
  }
end

local function plot_summary(plot, player_id)
  local terrain_type = safe_call(function() return plot:GetTerrainType() end, -1)
  local feature_type = safe_call(function() return plot:GetFeatureType() end, -1)
  local resource_type = safe_call(function() return plot:GetResourceType() end, -1)
  local improvement_type = safe_call(function() return plot:GetImprovementType() end, -1)
  return {
    index = safe_call(function() return plot:GetIndex() end, nil),
    x = safe_call(function() return plot:GetX() end, nil),
    y = safe_call(function() return plot:GetY() end, nil),
    terrain = type_name(GameInfo.Terrains, terrain_type),
    feature = type_name(GameInfo.Features, feature_type),
    resource = type_name(GameInfo.Resources, resource_type),
    improvement = type_name(GameInfo.Improvements, improvement_type),
    owner = safe_call(function() return plot:GetOwner() end, -1),
    is_city = safe_call(function() return plot:IsCity() end, false),
    is_water = safe_call(function() return plot:IsWater() end, false),
    is_revealed = safe_call(function() return plot:IsRevealed(player_id) end, nil)
  }
end

local function collect_units(player)
  local units = {}
  local player_units = safe_call(function() return player:GetUnits() end, nil)
  if player_units == nil or player_units.Members == nil then
    return units
  end
  for _, unit in player_units:Members() do
    table.insert(units, unit_summary(unit))
  end
  return units
end

local function collect_cities(player)
  local cities = {}
  local player_cities = safe_call(function() return player:GetCities() end, nil)
  if player_cities == nil or player_cities.Members == nil then
    return cities
  end
  for _, city in player_cities:Members() do
    table.insert(cities, city_summary(city))
  end
  return cities
end

local function collect_visible_plots(player_id)
  local plots = {}
  local plot_count = safe_call(function() return Map.GetPlotCount() end, 0)
  for index = 0, plot_count - 1 do
    local plot = safe_call(function() return Map.GetPlotByIndex(index) end, nil)
    if plot ~= nil then
      local revealed = safe_call(function() return plot:IsRevealed(player_id) end, false)
      if revealed then
        table.insert(plots, plot_summary(plot, player_id))
      end
    end
  end
  return plots
end

function Bridge.BuildState()
  local player_id = active_player_id()
  local player = Players[player_id]
  local width = safe_call(function()
    local w, _ = Map.GetGridSize()
    return w
  end, nil)
  local height = safe_call(function()
    local _, h = Map.GetGridSize()
    return h
  end, nil)
  return {
    schema = "civ6-agent-state-v0",
    game = {
      turn = safe_call(function() return Game.GetCurrentGameTurn() end, nil),
      local_player = safe_call(function() return Game.GetLocalPlayer() end, nil),
      local_observer = safe_call(function() return Game.GetLocalObserver() end, nil),
      map_width = width,
      map_height = height
    },
    player = player_summary(player_id),
    units = player and collect_units(player) or {},
    cities = player and collect_cities(player) or {},
    visible_plots = player and collect_visible_plots(player_id) or {}
  }
end

function Bridge.DumpState()
  local state = Bridge.BuildState()
  print(STATE_PREFIX .. encode_json(state))
  return state
end

function Bridge.DumpStateForEvent(event_name)
  print(STATUS_PREFIX .. tostring(event_name))
  return Bridge.DumpState()
end

function Bridge.MoveUnit(unit_id, x, y)
  local unit = get_unit(unit_id)
  if unit == nil then
    return command_result("MoveUnit", false, { error = "unit not found", unit_id = unit_id })
  end
  local parameters = {}
  parameters[UnitOperationTypes.PARAM_X] = x
  parameters[UnitOperationTypes.PARAM_Y] = y
  parameters[UnitOperationTypes.PARAM_MODIFIERS] =
    UnitOperationMoveModifiers.ATTACK + UnitOperationMoveModifiers.MOVE_IGNORE_UNEXPLORED_DESTINATION
  local can_start = safe_call(function()
    return UnitManager.CanStartOperation(unit, UnitOperationTypes.MOVE_TO, nil, parameters)
  end, nil)
  if can_start == false then
    return command_result("MoveUnit", false, {
      error = "UnitManager.CanStartOperation returned false",
      unit_id = unit_id,
      x = x,
      y = y,
    })
  end
  local requested = safe_call(function()
    UnitManager.RequestOperation(unit, UnitOperationTypes.MOVE_TO, parameters)
    return true
  end, false)
  return command_result("MoveUnit", requested, {
    unit_id = unit_id,
    x = x,
    y = y,
    can_start = can_start,
  })
end

function Bridge.FoundCity(unit_id)
  local unit = get_unit(unit_id)
  if unit == nil then
    return command_result("FoundCity", false, { error = "unit not found", unit_id = unit_id })
  end
  local can_start = safe_call(function()
    return UnitManager.CanStartOperation(unit, UnitOperationTypes.FOUND_CITY)
  end, nil)
  if can_start == false then
    return command_result("FoundCity", false, {
      error = "UnitManager.CanStartOperation returned false",
      unit_id = unit_id,
    })
  end
  local requested = safe_call(function()
    UnitManager.RequestOperation(unit, UnitOperationTypes.FOUND_CITY)
    return true
  end, false)
  return command_result("FoundCity", requested, { unit_id = unit_id, can_start = can_start })
end

function Bridge.SetCityProduction(city_id, production_type, production_kind)
  local city = get_city(city_id)
  if city == nil then
    return command_result("SetCityProduction", false, { error = "city not found", city_id = city_id })
  end
  local parameters = {}
  local kind, resolved_type, hash = apply_production_parameter(parameters, production_type, production_kind)
  if kind == nil then
    return command_result("SetCityProduction", false, {
      error = "unknown production target",
      city_id = city_id,
      target = production_type,
      kind = production_kind,
    })
  end
  parameters[CityOperationTypes.PARAM_INSERT_MODE] = CityOperationTypes.VALUE_EXCLUSIVE
  local can_start = safe_call(function()
    return CityManager.CanStartOperation(city, CityOperationTypes.BUILD, parameters, true)
  end, nil)
  if can_start == false then
    return command_result("SetCityProduction", false, {
      error = "CityManager.CanStartOperation returned false",
      city_id = city_id,
      target = production_type,
      resolved_type = resolved_type,
      kind = kind,
    })
  end
  local requested = safe_call(function()
    CityManager.RequestOperation(city, CityOperationTypes.BUILD, parameters)
    return true
  end, false)
  return command_result("SetCityProduction", requested, {
    city_id = city_id,
    target = production_type,
    resolved_type = resolved_type,
    target_hash = hash,
    kind = kind,
    can_start = can_start,
  })
end

function Bridge.SetResearch(tech_type)
  local tech = game_info_row(GameInfo.Technologies, tech_type)
  if tech == nil then
    return command_result("SetResearch", false, { error = "unknown technology", tech = tech_type })
  end
  local parameters = {}
  parameters[PlayerOperations.PARAM_TECH_TYPE] = tech.Hash
  parameters[PlayerOperations.PARAM_INSERT_MODE] = PlayerOperations.VALUE_EXCLUSIVE
  local requested = safe_call(function()
    UI.RequestPlayerOperation(active_player_id(), PlayerOperations.RESEARCH, parameters)
    return true
  end, false)
  return command_result("SetResearch", requested, {
    tech = tech_type,
    resolved_type = tech.TechnologyType,
    tech_hash = tech.Hash,
  })
end

function Bridge.EndTurn()
  local can_end = safe_call(function() return UI.CanEndTurn() end, nil)
  local requested = safe_call(function()
    UI.RequestAction(ActionTypes.ACTION_ENDTURN)
    return true
  end, false)
  return command_result("EndTurn", requested, { can_end_turn = can_end })
end

ExposedMembers.Civ6AgentBridge = Bridge

local function on_player_turn_activated(player_id, is_first_time_this_turn)
  g_last_active_player = player_id
  if is_first_time_this_turn then
    Bridge.DumpStateForEvent("PlayerTurnActivated:" .. tostring(player_id))
  end
end

local function on_local_player_changed(player_id, previous_player_id)
  g_last_active_player = player_id
  Bridge.DumpStateForEvent("LocalPlayerChanged:" .. tostring(previous_player_id) .. "->" .. tostring(player_id))
end

if Events ~= nil then
  if Events.PlayerTurnActivated ~= nil then
    Events.PlayerTurnActivated.Add(on_player_turn_activated)
  end
  if Events.LocalPlayerChanged ~= nil then
    Events.LocalPlayerChanged.Add(on_local_player_changed)
  end
  if Events.LoadGameViewStateDone ~= nil then
    Events.LoadGameViewStateDone.Add(function() Bridge.DumpStateForEvent("LoadGameViewStateDone") end)
  end
end

print("CIV6_AGENT_BRIDGE_READY")
Bridge.DumpStateForEvent("BridgeLoaded")
