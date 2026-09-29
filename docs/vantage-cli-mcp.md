# Vantage CLI and MCP

The Windows installer ships a `vantage` command alongside the already-bundled
Vantage backend. It does not install or copy a second Python runtime, and the
command never starts the Electron window or a second backend server.

```powershell
vantage --help
vantage system status read --format json
vantage mcp
```

`vantage mcp` runs the official MCP stdio transport. Vantage must already be
running; the command checks backend readiness and exits with an actionable
message if it cannot connect. MCP protocol data stays on stdout, so do not pipe
other output into that stream.

For source development, use `python -m src.cli --help` and
`python -m src.cli mcp`. The source MCP command has the same running-backend
requirement. Neither entry point contains an AI agent loop; an external client
chooses and invokes the exposed operations.

The installer adds only its dedicated `resources\cli-bin` directory to the
current Windows user's PATH. It preserves unrelated PATH entries, avoids
duplicate entries on upgrades, and removes only that Vantage directory during
uninstall. If a Windows policy prevents the PATH update, the installer still
completes and reports where `vantage.cmd` is located. Open a new terminal after
installing so it sees the updated PATH.

For operations with sensitive inputs, prefer `--input-json -` and pipe a JSON
object through stdin rather than placing secrets in shell history or process
arguments. CLI and MCP operations use the shared product catalog and backend
client; catalog entries marked unavailable remain discoverable and return the
catalog's reason when invoked.

The reusable Vantage workflow guide is `.agents/skills/vantage/SKILL.md`; its
project memory lives in `docs/vantage-project-memory.md` and documents the
shared operation map, safe settings updates, and UI-only behavior.
