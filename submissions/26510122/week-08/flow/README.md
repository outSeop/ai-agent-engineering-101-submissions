# R3 flow review

`agent-flow.html` is an interactive visualization fragment. Open
`agent-flow-standalone.html` in a browser for the standalone version.

The view has four flows: inventory, seller, buyer and the whole market relationship.
The default inventory view shows the intended model → calculation tool → model
decision loop. Switch the basis to current code to inspect the implementation
reviewed on 2026-11-02. Status labels distinguish implemented behavior, the agreed
direction, unresolved proposals and market/kit rules.

Select a node to inspect inputs, outputs and outgoing conditions. Select a condition
to follow its destination. The editor changes a node's fields and its outgoing
conditions/destinations. Changes are stored in the available browser/host state.
Export the JSON text to keep a portable copy, or import saved JSON through the text
field or file picker. Nothing in the editor changes the running trading code:
conditions are explanatory text, not executable predicates.

## Updating the checked-in source

`flow-spec.json` is the source of truth for the checked-in diagrams. JSON exported
by the editor can replace that file after review. `flow-template.html` contains
the renderer and editor. Regenerate the fragment with:

```bash
python3 flow/build_flow.py
```

To also regenerate the standalone wrapper, pass the installed visualize skill's
`scripts/render.py` as `--renderer`:

```bash
python3 flow/build_flow.py --renderer /path/to/visualize/scripts/render.py
```

The standalone wrapper is generated and self-contained. Its only host calls are
the optional `window.openai.widgetState`/`setWidgetState` state bridge.

## Browser checks

```bash
uv run --with playwright python flow/check_flow.py
```

The check uses the installed macOS Chrome. It exercises node/edge editing,
JSON round trips, reload persistence, invalid input, all flow/basis combinations,
mobile layout and light/dark appearance. This is a design-review aid, not a
simulation of demand, an evaluation of economic performance or the required
LaTeX architecture figure for the assignment.
