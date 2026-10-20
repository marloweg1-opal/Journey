# mini_ark Navigator — implementation handoff

## Canonical rules

1. `reference/LOCKED_mini_ark_navigator_visual_spec.png` is the **locked visual specification**.
2. `reference/mini_ark_navigator_extraction_map.png` is the **extraction / decomposition map**.
3. `index.html + styles.css + app.js + assets/` are the **rebuilt interface**.

The master reference and extraction sheet are **never** to be used as a scaled page background or flattened clickable screenshot.

## Production behavior

- All user-facing text is native HTML.
- Search is a real `<input>`.
- FIND / LAUNCH / GUIDE / MANAGE are real buttons.
- Zodiac symbols are separate image assets.
- Decorative crystal art is separate from functional copy.
- Home remains compact.
- Dense panels appear only when a mode is invoked.
- Ctrl + Alt + A focuses search.
- Launch actions are currently exposed as copyable commands so this static prototype cannot silently execute local shell commands.

## Backend bridge

This prototype is deliberately frontend-only. The next local integration should replace seeded search data and copy-only launch actions with the existing mini_ark local server / launcher endpoints.

Do **not** rewrite the UI around backend limitations. Add a thin bridge layer.

Suggested bridge contract:

```js
window.miniArkBridge = {
  search(query) -> Promise<{tools:[], guides:[], memory:[]}>,
  launch(actionId, args?) -> Promise<{ok:boolean, message:string}>,
  status() -> Promise<{state:string, tests:string, git:string, environment:string}>
}
```

## Existing command surface represented in the prototype

- `powershell -ExecutionPolicy Bypass -File .\start_mini_ark.ps1`
- `.\ark.cmd doctor`
- `.\ark.cmd brief`
- `.\ark.cmd inventory --under R:\`
- `.\ark.cmd scan <path>`
- `.\ark.cmd ingest <export-file>`
- `python -m unittest discover -s tests`

Any destructive or filesystem-changing action should preserve mini_ark's existing explicit review / approval / undo model.
