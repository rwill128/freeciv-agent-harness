# Freeciv MCP Artifact Mode

MCP artifact mode lets an experiment move tool-result data out of the model's
immediate context and onto the filesystem. The agent receives a file path and
can inspect the result with normal file reads, shell tools, or ad-hoc scripts.

This is meant to test the hypothesis that agents perform better when bulky data
is available as files instead of being injected directly into every tool-call
result.

## Why This Exists

Some Freeciv data is too large or too structured for a clean conversational
tool result:

- full decoded player snapshots;
- known tile maps;
- ruleset object tables;
- unit type, terrain, extra, building, and technology tables;
- production target lists with requirements and legality details;
- local map views at larger radii;
- movement/action legality dumps;
- message history;
- packet/event counts and decoded protocol state.

Those are valuable for decision-making, but dumping them into the LLM context on
every inspection can waste context and force the model to reason over data it
may not need. Artifact mode preserves the data while letting the agent choose
how deeply to inspect it.

## Modes

The MCP server supports three modes:

| Mode | Behavior |
| --- | --- |
| `off` | Default. Return MCP tool results normally. No files are written. |
| `mirror` | Return the full MCP result and also write it to a file. |
| `file-only` | Write the full result to a file and return only file metadata plus a short preview. |

`file-only` is the cleanest mode for testing filesystem-resident data, because
the full result does not flood the tool-call context.

## File Location

By default, artifacts are written under the scoped player's workspace:

```text
players/<AgentName>/mcp-artifacts/
```

Example:

```text
players/AgentD/mcp-artifacts/20260705T171212.123456Z-0003-state_snapshot.txt
players/AgentD/mcp-artifacts/20260705T171212.123456Z-0003-state_snapshot.metadata.json
```

The directory is created with mode `0700` when possible. The important isolation
property for the harness is that the path is inside the current player's
workspace and the MCP server itself is player-scoped. This is not a hard OS user
isolation boundary if all agents run as the same local user with full sandbox
bypass.

## Metadata

Every artifact writes:

- `<artifact>.txt`: full tool result text.
- `<artifact>.metadata.json`: player, tool name, arguments, interface version,
  artifact mode, timestamp, byte count, and text file path.

The text file contains exactly the string that would otherwise be returned by
the MCP tool before artifact wrapping.

## Starting MCP Directly

```bash
scripts/freeciv-mcp \
  --player AgentD \
  --control-url http://127.0.0.1:8787 \
  --interface-version v2 \
  --artifact-mode file-only \
  --artifact-preview-chars 800
```

Environment equivalents:

```bash
FREECIV_MCP_ARTIFACT_MODE=file-only
FREECIV_MCP_ARTIFACT_PREVIEW_CHARS=800
FREECIV_MCP_ARTIFACT_DIR=/custom/path
```

## Starting A Match

```bash
PLAYERS="AgentA AgentB AgentC AgentD" \
MCP_PLAYERS="AgentC AgentD" \
MCP_VERSIONS="AgentC=v2 AgentD=v2" \
MCP_ARTIFACT_MODE=file-only \
MCP_ARTIFACT_PREVIEW_CHARS=800 \
MODEL=gpt-5.5 \
scripts/start-fresh-match
```

`MCP_ARTIFACT_MODE` applies to all MCP players in that match. CLI players are
unchanged.

## Recommended Experiment Comparisons

Good comparisons:

- MCP v2 with artifact mode `off` vs MCP v2 with artifact mode `file-only`.
- MCP v1 `off` vs MCP v1 `mirror`, to see whether filesystem mirroring helps
  even when context is still flooded.
- MCP v2 `file-only` with normal prompt vs MCP v2 `file-only` with structured
  prompt requiring shell/file inspection.

Keep model, victory mode, ruleset, map settings, and turn timeout fixed.

## Bulk Tool: `state_snapshot`

`v2` includes a `state_snapshot` tool for full decoded player-visible state.
This tool is intentionally bulky and is best used with artifact mode `mirror` or
`file-only`.

It calls:

```text
GET /players/<player>
```

The snapshot can include:

- player identity and connection state;
- ruleset summary;
- map topology;
- all currently known tiles for that player;
- visible owned units and cities;
- decoded unit types;
- decoded buildings;
- decoded terrain types;
- decoded extras/resources/improvements;
- decoded technologies;
- research state;
- recent visible messages;
- packet counts and last error.

This is the closest current equivalent of "all bulk decision data known to this
player right now."
