# EvalGlass diagrams

Two hand-drawn (Excalidraw-style) diagrams that help a developer grasp EvalGlass quickly. Each ships
as an editable [Excalidraw](https://excalidraw.com) scene (`.excalidraw`), a vector `.svg`, and a
`.png` (the sketch rendering used in the top-level `README.md`, so the hand-drawn font renders the
same for everyone).

| Diagram | Shows |
|---|---|
| `evalglass-authority` | The trust boundary (the README's lead diagram): **you** decide and gate, your **coding agent** operates but never authorizes, **EvalGlass** measures and reports. Capability is not authority. |
| `evalglass-pipeline` | The data flow: your evidence → Runtime Harness → Evaluation Core → the single Verdict Engine → `scorecard.json` / `runrecord.json` / reports / CI exit. |

**Edit:** open the `.excalidraw` file at [excalidraw.com](https://excalidraw.com) (or the VS Code
Excalidraw extension), change it, then re-export so the README stays in sync.
