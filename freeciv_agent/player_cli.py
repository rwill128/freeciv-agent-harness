from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    player = os.environ.get("FREECIV_PLAYER_NAME")
    if not player:
        raise SystemExit("FREECIV_PLAYER_NAME is required")

    base_url = os.environ.get("FREECIV_CONTROL_URL", DEFAULT_BASE_URL).rstrip("/")

    parser = argparse.ArgumentParser(
        description=f"Player-scoped Freeciv CLI for {player}."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("whoami")
    subparsers.add_parser("ruleset")
    production_targets = subparsers.add_parser("production-targets")
    production_targets.add_argument(
        "--json",
        action="store_true",
        help="Emit full verbose production target JSON instead of compact text.",
    )
    production_targets.add_argument(
        "--all",
        action="store_true",
        help="Include every decoded unit and building target in text output.",
    )
    production_targets.add_argument(
        "--city-id",
        type=int,
        help="Include city-specific advisory legality for this city.",
    )
    brief = subparsers.add_parser("brief")
    brief.add_argument(
        "--json",
        action="store_true",
        help="Emit the full verbose brief JSON instead of the compact text view.",
    )
    subparsers.add_parser("state")

    messages = subparsers.add_parser("messages")
    messages.add_argument("--limit", default=20, type=int)

    local_view = subparsers.add_parser("local-view")
    add_view_args(local_view, default_radius=2)

    ascii_view = subparsers.add_parser("ascii-view")
    add_view_args(ascii_view, default_radius=3)
    ascii_view.add_argument("--text", action="store_true")

    valid_moves = subparsers.add_parser("valid-moves")
    valid_moves.add_argument("unit_id", type=int)
    valid_moves.add_argument(
        "--json",
        action="store_true",
        help="Emit the full verbose valid-moves JSON instead of the compact text view.",
    )

    ready = subparsers.add_parser("ready")
    ready.add_argument("--not-ready", action="store_true")

    say = subparsers.add_parser("say")
    say.add_argument("message")

    private_intent = subparsers.add_parser("private-intent")
    private_intent.add_argument("intent")
    private_intent.add_argument("--turn", type=int)

    narrative = subparsers.add_parser("narrative")
    narrative.add_argument("entry")

    phase_done = subparsers.add_parser("phase-done")
    phase_done.add_argument("--turn", type=int)
    phase_done.add_argument("--intent")
    phase_done.add_argument("--wait", default=2.0, type=float)

    found_city = subparsers.add_parser("found-city")
    found_city.add_argument("--unit-id", type=int)
    found_city.add_argument("--city-name", default="")
    found_city.add_argument("--wait", default=5.0, type=float)

    move_unit = subparsers.add_parser("move-unit")
    move_unit.add_argument("unit_id", type=int)
    move_unit.add_argument("--target-tile", type=int)
    move_unit.add_argument("--direction", type=int)
    move_unit.add_argument("--dx", default=0, type=int)
    move_unit.add_argument("--dy", default=0, type=int)
    move_unit.add_argument("--wait", default=5.0, type=float)

    unit_activity = subparsers.add_parser("unit-activity")
    unit_activity.add_argument("unit_id", type=int)
    unit_activity.add_argument("activity")
    unit_activity.add_argument("--target")
    unit_activity.add_argument("--wait", default=5.0, type=float)
    unit_activity.add_argument(
        "--json",
        action="store_true",
        help="Emit the full verbose unit-activity JSON instead of compact text.",
    )

    set_city_production = subparsers.add_parser("set-city-production")
    set_city_production.add_argument("city_id", type=int)
    set_city_production.add_argument("target")
    set_city_production.add_argument("--kind", default="unit")
    set_city_production.add_argument("--wait", default=1.0, type=float)

    set_rates = subparsers.add_parser("set-rates")
    set_rates.add_argument("--tax", required=True, type=int)
    set_rates.add_argument("--luxury", required=True, type=int)
    set_rates.add_argument("--science", required=True, type=int)
    set_rates.add_argument("--wait", default=1.0, type=float)

    set_research = subparsers.add_parser("set-research")
    set_research.add_argument("tech")
    set_research.add_argument("--wait", default=1.0, type=float)

    set_tech_goal = subparsers.add_parser("set-tech-goal")
    set_tech_goal.add_argument("tech")
    set_tech_goal.add_argument("--wait", default=1.0, type=float)

    query_actions = subparsers.add_parser("query-actions")
    query_actions.add_argument("unit_id", type=int)
    query_actions.add_argument("--target-tile", type=int)
    query_actions.add_argument("--dx", default=0, type=int)
    query_actions.add_argument("--dy", default=0, type=int)

    do_action = subparsers.add_parser("do-action")
    do_action.add_argument("unit_id", type=int)
    do_action.add_argument("action")
    do_action.add_argument("--target-id", required=True, type=int)
    do_action.add_argument("--sub-target", default=-1, type=int)
    do_action.add_argument("--action-name", default="")
    do_action.add_argument("--wait", default=1.0, type=float)

    args = parser.parse_args()

    result: Any
    if args.command == "whoami":
        result = {"player": player, "control_url": base_url}
    elif args.command == "ruleset":
        result = request("GET", f"{base_url}/ruleset")
    elif args.command == "production-targets":
        url = f"{base_url}/players/{quoted(player)}/production-targets"
        if args.city_id is not None:
            url += f"?city_id={args.city_id}"
        result = request("GET", url)
        if not args.json:
            print(format_production_targets(result, show_all=args.all))
            return
    elif args.command == "brief":
        result = request("GET", f"{base_url}/players/{quoted(player)}/brief")
        if not args.json:
            print(format_brief(result))
            return
    elif args.command == "state":
        result = request("GET", f"{base_url}/players/{quoted(player)}")
    elif args.command == "messages":
        result = request(
            "GET",
            f"{base_url}/players/{quoted(player)}/messages?"
            f"{urllib.parse.urlencode({'limit': args.limit})}",
        )
    elif args.command == "local-view":
        result = get_view(base_url, player, "local-view", args)
    elif args.command == "ascii-view":
        result = get_view(base_url, player, "ascii-view", args)
        if args.text:
            print(result["text"])
            return
    elif args.command == "valid-moves":
        result = request(
            "GET",
            f"{base_url}/players/{quoted(player)}/valid-moves?"
            f"{urllib.parse.urlencode({'unit_id': args.unit_id})}",
        )
        if not args.json:
            print(format_valid_moves(result))
            return
    elif args.command == "ready":
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/ready",
            {"is_ready": not args.not_ready},
        )
    elif args.command == "say":
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/say",
            {"message": args.message},
        )
    elif args.command == "private-intent":
        body: dict[str, Any] = {"intent": args.intent}
        if args.turn is not None:
            body["turn"] = args.turn
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/private-intent",
            body,
        )
    elif args.command == "narrative":
        result = append_narrative(player, args.entry)
    elif args.command == "phase-done":
        body: dict[str, Any] = {}
        if args.turn is not None:
            body["turn"] = args.turn
        if args.intent is not None:
            body["intent"] = args.intent
        body["wait"] = args.wait
        result = request("POST", f"{base_url}/players/{quoted(player)}/phase-done", body)
    elif args.command == "found-city":
        body = {"city_name": args.city_name}
        if args.unit_id is not None:
            body["unit_id"] = args.unit_id
        body["wait"] = args.wait
        result = request("POST", f"{base_url}/players/{quoted(player)}/found-city", body)
    elif args.command == "move-unit":
        body = {
            "unit_id": args.unit_id,
            "dx": args.dx,
            "dy": args.dy,
            "wait": args.wait,
        }
        if args.target_tile is not None:
            body["target_tile"] = args.target_tile
        if args.direction is not None:
            body["direction"] = args.direction
        result = request("POST", f"{base_url}/players/{quoted(player)}/move-unit", body)
    elif args.command == "unit-activity":
        body = {
            "unit_id": args.unit_id,
            "activity": args.activity,
            "wait": args.wait,
        }
        if args.target is not None:
            body["target"] = args.target
        result = request("POST", f"{base_url}/players/{quoted(player)}/unit-activity", body)
        if not args.json:
            print(format_unit_activity_result(result))
            return
    elif args.command == "set-city-production":
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/set-city-production",
            {
                "city_id": args.city_id,
                "target": args.target,
                "kind": args.kind,
                "wait": args.wait,
            },
        )
    elif args.command == "set-rates":
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/set-rates",
            {
                "tax": args.tax,
                "luxury": args.luxury,
                "science": args.science,
                "wait": args.wait,
            },
        )
    elif args.command == "set-research":
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/set-research",
            {"tech": args.tech, "wait": args.wait},
        )
    elif args.command == "set-tech-goal":
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/set-tech-goal",
            {"tech": args.tech, "wait": args.wait},
        )
    elif args.command == "query-actions":
        body = {"unit_id": args.unit_id, "dx": args.dx, "dy": args.dy}
        if args.target_tile is not None:
            body["target_tile"] = args.target_tile
        result = request("POST", f"{base_url}/players/{quoted(player)}/query-actions", body)
    elif args.command == "do-action":
        result = request(
            "POST",
            f"{base_url}/players/{quoted(player)}/do-action",
            {
                "unit_id": args.unit_id,
                "target_id": args.target_id,
                "action": args.action,
                "sub_target": args.sub_target,
                "name": args.action_name,
                "wait": args.wait,
            },
        )
    else:
        raise AssertionError(args.command)

    finish_result(result)


def append_narrative(player: str, entry: str) -> dict[str, Any]:
    workspace = ROOT / "players" / player
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "narrative.md"
    text = entry.strip()
    if not text:
        raise SystemExit("narrative entry cannot be empty")
    if not text.startswith("#"):
        stamp = datetime.now().isoformat(timespec="seconds")
        text = f"## {stamp}\n\n{text}"
    payload = text.rstrip() + "\n\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
    return {
        "ok": True,
        "player": player,
        "path": str(path),
        "bytes_appended": len(payload.encode("utf-8")),
    }


def finish_result(result: Any) -> None:
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    print()
    if isinstance(result, dict) and result.get("ok") is False:
        raise SystemExit(1)


def format_brief(result: dict[str, Any]) -> str:
    phase = result.get("phase") or {}
    economy = result.get("economy") or {}
    research = result.get("research") or {}
    ruleset = result.get("ruleset") or {}
    active = phase.get("agent_is_active_phase")
    lines = [
        (
            f"{result.get('name')} turn {result.get('turn')} year {result.get('year')} "
            f"active_phase={active} phase={phase.get('mode_name')}"
        )
    ]
    if active is False:
        lines.append("Status: not this player's active phase; do not act until active.")
    if ruleset:
        lines.append(
            "Ruleset: "
            f"rulesetdir={ruleset.get('rulesetdir')} "
            f"rules_doc=docs/freeciv-rules-for-agents.md"
        )
    production_targets = result.get("production_targets") or {}
    target_summary = format_key_unit_target_summary(production_targets)
    if target_summary:
        lines.append(
            "Key production targets: "
            f"{target_summary}. Full exact list: bin/game production-targets"
        )
    lines.append(
        "Economy: "
        f"gold={economy.get('gold')} tax={economy.get('tax')} "
        f"science={economy.get('science')} luxury={economy.get('luxury')}"
    )
    lines.append("Player status: " + format_player_status(result.get("player_status") or {}))
    researching = research.get("researching_info") or {}
    if research:
        lines.append(
            "Research: "
            f"{researching.get('name') or researching.get('rule_name') or research.get('researching')} "
            f"cost={research.get('researching_cost')} "
            f"known_techs={len(research.get('known') or [])}"
        )
    cities = result.get("cities") or []
    if cities:
        lines.append("Cities:")
        for city in cities:
            production = city.get("production") or {}
            command_target = production.get("command_target") or production.get("rule_name")
            lines.append(
                "  "
                f"{city.get('id')}:{city.get('name')} tile={city.get('tile')} "
                f"size={city.get('size')} food={city.get('food_stock')} "
                f"shields={city.get('shield_stock')} "
                f"producing={clean_label(production.get('name') or production.get('rule_name'))} "
                f"command_target={command_target}"
            )
    else:
        lines.append("Cities: none")

    units = result.get("units") or []
    actionable = [
        unit for unit in units
        if isinstance(unit.get("movesleft"), int) and unit.get("movesleft", 0) > 0
    ]
    inactive = [unit for unit in units if unit not in actionable]
    lines.append(f"Units needing attention (movesleft > 0): {len(actionable)}")
    if actionable:
        for unit in sorted(actionable, key=lambda item: (-int(item.get("movesleft", 0)), int(item.get("id", 0)))):
            lines.append("  " + format_brief_unit(unit))
    else:
        lines.append("  none")
    lines.append(f"Other units: {len(inactive)}")
    for unit in sorted(inactive, key=lambda item: int(item.get("id", 0))):
        lines.append("  " + format_brief_unit(unit))
    lines.append("Inspect units with: bin/game valid-moves <unit_id> or bin/game ascii-view --unit-id <unit_id> --text")
    return "\n".join(lines)


def format_player_status(status: dict[str, Any]) -> str:
    if not status or not status.get("available"):
        return "PACKET_PLAYER_INFO status unavailable"
    identity = status.get("identity") or {}
    connection = status.get("connection") or {}
    lifecycle = status.get("lifecycle") or {}
    flags = status.get("flags") or {}
    style = status.get("style") or {}
    visibility = status.get("visibility") or {}
    attitudes = status.get("ai_attitudes") or {}
    wonders = status.get("wonders") or {}
    multipliers = status.get("multipliers") or {}
    parts = [
        f"player_no={identity.get('player_no')}",
        f"team={identity.get('team_id')}",
    ]
    if connection.get("is_connected") is not None:
        parts.append(f"connected={connection.get('is_connected')}")
    if connection.get("phase_done") is not None:
        parts.append(f"phase_done={connection.get('phase_done')}")
    if lifecycle.get("is_alive") is not None:
        parts.append(f"alive={lifecycle.get('is_alive')}")
    active_flags = [
        str(item.get("name"))
        for item in flags.get("active") or []
        if item.get("name")
    ]
    parts.append(f"flags={','.join(active_flags) if active_flags else 'none'}")
    for key, label in (
        ("real_embassy", "embassies"),
        ("gives_shared_vision", "shared_vision"),
        ("gives_shared_tiles", "shared_tiles"),
    ):
        item = visibility.get(key) or {}
        if item.get("active_count"):
            parts.append(f"{label}={item.get('active_count')}")
    color = style.get("color_rgb") or {}
    if color.get("css_hex"):
        parts.append(f"color={color.get('css_hex')}")
    if style.get("style_id") is not None:
        parts.append(f"style_id={style.get('style_id')}")
    if attitudes.get("available"):
        parts.append(f"non_neutral_ai_attitudes={attitudes.get('non_neutral_count', 0)}")
    if wonders.get("available"):
        if wonders.get("encoding") == "flat_player_wonders_array":
            parts.append(f"wonders_built_or_lost={wonders.get('built_or_lost_count', 0)}")
        else:
            parts.append(f"wonders_encoding={wonders.get('encoding')}")
    if multipliers.get("available"):
        parts.append(f"multipliers={multipliers.get('count', 0)}")
    return " ".join(parts)


def format_key_unit_target_summary(production_targets: dict[str, Any]) -> str:
    key_units = production_targets.get("key_unit_targets") or {}
    if key_units:
        parts = []
        for role, targets in key_units.items():
            names = [
                str(target.get("target"))
                for target in targets
                if target.get("target")
            ]
            if names:
                parts.append(f"{role}={','.join(names[:4])}")
        return "; ".join(parts)
    common_targets = production_targets.get("common_unit_targets") or []
    return ", ".join(
        str(target.get("target"))
        for target in common_targets[:8]
        if target.get("target")
    )


def format_production_targets(result: dict[str, Any], *, show_all: bool = False) -> str:
    usage = result.get("usage") or {}
    lines = [
        "Production targets use exact ruleset names.",
        usage.get("target_rule") or "Use the target value exactly as shown.",
        f"Unit command: {usage.get('unit')}",
        f"Building command: {usage.get('building')}",
    ]
    if result.get("city_id") is not None:
        city = result.get("city") or {}
        production = city.get("production") or {}
        lines.append(
            "City-specific legality: "
            f"city={result.get('city_id')} {city.get('name')} size={city.get('size')} "
            f"current={production.get('command_target') or production.get('name')}"
        )
        lines.append(str(result.get("city_specific_legality")))
    key_units = result.get("key_unit_targets") or {}
    if key_units:
        lines.append("Key unit targets by role:")
        for role, targets in key_units.items():
            if not targets:
                continue
            lines.append(f"  {role}:")
            for target in targets:
                lines.append("    " + format_production_target_line(target))
    else:
        common_units = result.get("common_unit_targets") or []
        if common_units:
            lines.append("Common unit targets:")
            for target in common_units:
                lines.append("  " + format_production_target_line(target))
    counts = result.get("counts") or {}
    lines.append(
        "Full list: "
        f"{counts.get('unit')} unit targets and {counts.get('building')} building targets. "
        "Run `bin/game production-targets --all` to print them."
    )
    if not show_all:
        return "\n".join(lines)
    unit_targets = result.get("unit_targets") or []
    building_targets = result.get("building_targets") or []
    if unit_targets:
        lines.append(f"All unit targets ({len(unit_targets)}):")
        for target in unit_targets:
            lines.append("  " + format_production_target_line(target))
    if building_targets:
        lines.append(f"All building targets ({len(building_targets)}):")
        for target in building_targets:
            lines.append("  " + format_production_target_line(target))
    return "\n".join(lines)


def format_production_target_line(target: dict[str, Any]) -> str:
    parts = [
        f"{target.get('target')}",
        f"id={target.get('id')}",
        f"kind={target.get('kind')}",
    ]
    if target.get("build_cost") is not None:
        parts.append(f"cost={target.get('build_cost')}")
    if target.get("pop_cost"):
        parts.append(f"pop_cost={target.get('pop_cost')}")
    roles = target.get("roles") or []
    if roles:
        parts.append("roles=" + ",".join(str(role) for role in roles))
    if "can_found_city" in target:
        parts.append(f"can_found_city={str(target.get('can_found_city')).lower()}")
    if target.get("note"):
        parts.append(f"note={target.get('note')}")
    combat = []
    if target.get("attack_strength") is not None:
        combat.append(f"atk={target.get('attack_strength')}")
    if target.get("defense_strength") is not None:
        combat.append(f"def={target.get('defense_strength')}")
    if combat:
        parts.append(" ".join(combat))
    requirements = target.get("build_requirements") or []
    if requirements:
        labels = [
            f"{req.get('kind')}:{req.get('value_name') or req.get('value')}"
            for req in requirements[:3]
        ]
        parts.append("requires=" + ",".join(labels))
    legality = target.get("legality") or {}
    if legality:
        blockers = legality.get("known_blockers") or []
        warnings = legality.get("warnings") or []
        parts.append(f"legality={legality.get('estimate')}")
        if blockers:
            parts.append("blockers=" + ";".join(str(item) for item in blockers))
        if warnings:
            parts.append("warnings=" + ";".join(str(item) for item in warnings))
    return " ".join(str(part) for part in parts)


def format_brief_unit(unit: dict[str, Any]) -> str:
    label = clean_label(unit.get("type_rule_name") or unit.get("type_name") or "unknown unit")
    activity = unit.get("activity_info") or {}
    parts = [
        f"{unit.get('id')}:{label}",
        f"tile={unit.get('tile')}",
        f"movesleft={unit.get('movesleft')}",
        f"hp={unit.get('hp')}",
    ]
    if unit.get("type_source"):
        parts.append(f"type={unit.get('type_source')}")
    notes = unit.get("type_notes") or []
    if notes:
        parts.append("note=" + " ".join(str(note) for note in notes))
    activity_name = activity.get("name")
    if activity_name:
        target = activity.get("target") or {}
        if isinstance(target, dict) and target.get("name"):
            parts.append(f"activity={activity_name}({clean_label(target.get('name'))})")
        else:
            parts.append(f"activity={activity_name}")
    return " ".join(str(part) for part in parts)


def format_valid_moves(result: dict[str, Any]) -> str:
    unit = result.get("unit") or {}
    unit_label = clean_label(unit.get("type_rule_name") or unit.get("type_name") or "unit")
    actionability = result.get("actionability") or {}
    current_map = result.get("current_map") or {}
    lines = [
        (
            f"{result.get('player')} turn {result.get('turn')}: "
            f"unit {unit.get('id')} ({unit_label}) at tile {result.get('current_tile')} "
            f"map=({current_map.get('x')},{current_map.get('y')}) "
            f"movesleft={unit.get('movesleft')}"
        ),
        (
            "Authority: advisory local estimates; `move-unit` sends topology-valid "
            "orders to Freeciv, which is final."
        ),
    ]
    reason = actionability.get("reason")
    if reason:
        lines.append(f"Can act now: {actionability.get('can_act_now')} ({reason})")
    lines.append("Moves:")
    for move in result.get("moves", []):
        lines.append("  " + format_move_line(move))
    return "\n".join(lines)


def format_unit_activity_result(result: dict[str, Any]) -> str:
    activity = result.get("activity_info") or {}
    target = result.get("target_info") or {}
    outcome = result.get("result") or {}
    retry = result.get("retry_policy") or {}
    before = result.get("before") or {}
    after = result.get("after") or {}
    activity_name = clean_label(activity.get("name") or result.get("activity"))
    target_name = clean_label(target.get("rule_name") or target.get("name"))
    requested = str(activity_name)
    if target_name:
        requested += f"({target_name})"

    lines = [
        (
            f"{result.get('player')}: unit {result.get('unit_id')} "
            f"unit-activity {requested}"
        ),
        (
            f"Result: {outcome.get('estimate')} "
            f"sent={result.get('sent')} applied={result.get('applied')} "
            f"observed_changed={result.get('observed_changed')}"
        ),
    ]
    if outcome.get("reason"):
        lines.append(f"Reason: {outcome.get('reason')}")
    if retry:
        repeat = "yes" if retry.get("repeat_same_order_this_turn") else "no"
        lines.append(f"Repeat same order this turn: {repeat}")
        if retry.get("next_step"):
            lines.append(f"Next step: {retry.get('next_step')}")
    if before:
        lines.append("Before: " + format_brief_unit(before))
    if after:
        lines.append("After: " + format_brief_unit(after))

    legality = result.get("legality") or {}
    blockers = summarize_blockers(legality.get("known_blockers") or [])
    if blockers:
        lines.append(f"Known blockers: {blockers}")
    warnings = legality.get("warnings") or []
    if warnings:
        lines.append("Warnings: " + "; ".join(str(item) for item in warnings))
    return "\n".join(lines)


def format_move_line(move: dict[str, Any]) -> str:
    direction = move.get("direction_info") or {}
    tile = move.get("tile") or {}
    legality = move.get("legality") or {}
    target_map = move.get("target_map") or {}
    terrain = clean_label(tile.get("terrain_rule_name") or tile.get("terrain_name") or "unknown terrain")
    resource = clean_label(tile.get("resource_rule_name") or tile.get("resource_name"))
    extras = [
        clean_label(extra.get("rule_name") or extra.get("name"))
        for extra in tile.get("extras_info", [])
        if isinstance(extra, dict) and clean_label(extra.get("rule_name") or extra.get("name"))
    ]
    known = "known" if move.get("known") else "unknown"
    pieces = [
        f"{direction.get('id')}:{direction.get('name')}",
        f"target={move.get('target_tile')}({target_map.get('x')},{target_map.get('y')})",
        f"{known}",
        terrain,
    ]
    if resource:
        pieces.append(f"resource={resource}")
    if extras:
        pieces.append("extras=" + ",".join(extras))
    movement_cost = tile.get("movement_cost")
    if movement_cost is not None:
        pieces.append(f"move_cost={movement_cost}")
    blockers = summarize_blockers(move.get("known_blockers") or legality.get("known_blockers") or [])
    if blockers:
        pieces.append(f"blockers={blockers}")
    warnings = move.get("warnings") or legality.get("warnings") or []
    if warnings:
        pieces.append("warnings=" + "; ".join(str(item) for item in warnings))
    estimate = legality.get("estimate", "unknown")
    reason = legality.get("reason")
    suffix = f"estimate={estimate}"
    if reason:
        suffix += f" - {reason}"
    return "; ".join(str(piece) for piece in pieces) + "; " + suffix


def summarize_blockers(blockers: list[Any]) -> str:
    labels = []
    for blocker in blockers:
        if not isinstance(blocker, dict):
            labels.append(str(blocker))
            continue
        kind = blocker.get("kind") or "blocker"
        label = blocker.get("name") or blocker.get("type") or blocker.get("id")
        relation = blocker.get("relation")
        if relation:
            labels.append(f"{kind}:{label}({relation})")
        else:
            labels.append(f"{kind}:{label}")
    return ", ".join(labels)


def clean_label(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("?") and ":" in value:
        return value.split(":", 1)[1]
    return value


def add_view_args(parser: argparse.ArgumentParser, *, default_radius: int) -> None:
    parser.add_argument("--unit-id", type=int)
    parser.add_argument("--city-id", type=int)
    parser.add_argument("--tile-id", type=int)
    parser.add_argument("--radius", default=default_radius, type=int)


def get_view(base_url: str, player: str, endpoint: str, args: argparse.Namespace) -> Any:
    query = {"radius": args.radius}
    if args.unit_id is not None:
        query["unit_id"] = args.unit_id
    if args.city_id is not None:
        query["city_id"] = args.city_id
    if args.tile_id is not None:
        query["tile_id"] = args.tile_id
    return request(
        "GET",
        f"{base_url}/players/{quoted(player)}/{endpoint}?{urllib.parse.urlencode(query)}",
    )


def quoted(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def request(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {"error": detail or exc.reason}
        json.dump(payload, sys.stderr, indent=2, sort_keys=True)
        print(file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        json.dump({"error": str(exc)}, sys.stderr, indent=2, sort_keys=True)
        print(file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
