# Corvia for VS Code

A thin VS Code extension that hosts the [`corvia-lsp`](https://github.com/kevintsou/Corvia) language server, giving you live MISRA C:2012 and bug diagnostics on every save.

## Prerequisites

The Python language server must be installed and on your `PATH`:

```bash
pip install 'corvia[lsp]'
which corvia-lsp     # should print a path
```

## Install (development)

```bash
cd extensions/vscode-corvia
npm install
npm run compile
```

Then in VS Code, run the **Developer: Install Extension from Location…** command and select this directory. Alternatively package and install:

```bash
npm run package          # produces vscode-corvia-0.1.0.vsix
code --install-extension vscode-corvia-0.1.0.vsix
```

## Settings

| Setting | Default | What it does |
|---|---|---|
| `corvia.serverPath` | `corvia-lsp` | Path to the language server binary |
| `corvia.transport` | `stdio` | `stdio` or `tcp` |
| `corvia.tcp.host` | `127.0.0.1` | TCP host (when `transport=tcp`) |
| `corvia.tcp.port` | `9999` | TCP port (when `transport=tcp`) |
| `corvia.trace.server` | `off` | LSP trace level: `off` / `messages` / `verbose` |

## Commands

- **Corvia: Restart Language Server** — kills and respawns `corvia-lsp`
- **Corvia: Show Output Channel** — opens the LSP transcript

## How it works

The extension activates on `c` / `cpp` documents, spawns `corvia-lsp --stdio` (or connects to a running instance over TCP), and forwards LSP requests via [vscode-languageclient](https://github.com/microsoft/vscode-languageserver-node). All diagnostics, code descriptions, and the project-level `corvia.toml` configuration come from the server itself — the extension contributes only the transport plumbing.
