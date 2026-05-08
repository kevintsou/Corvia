// VS Code extension that hosts the `corvia-lsp` Language Server.
//
// The server itself is shipped separately (`pip install corvia[lsp]`).
// This extension only spawns it and forwards requests through the
// vscode-languageclient transport.

import * as net from "net";
import {
  ExtensionContext,
  workspace,
  commands,
  window,
} from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  StreamInfo,
  TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

export async function activate(context: ExtensionContext): Promise<void> {
  await startClient(context);

  context.subscriptions.push(
    commands.registerCommand("corvia.restartServer", async () => {
      if (client) {
        await client.stop();
        client = undefined;
      }
      await startClient(context);
      window.showInformationMessage("Corvia language server restarted");
    }),
    commands.registerCommand("corvia.showOutput", () => {
      client?.outputChannel.show();
    }),
  );
}

export async function deactivate(): Promise<void> {
  if (client) {
    await client.stop();
    client = undefined;
  }
}

async function startClient(_context: ExtensionContext): Promise<void> {
  const cfg = workspace.getConfiguration("corvia");
  const serverPath = cfg.get<string>("serverPath", "corvia-lsp");
  const transport = cfg.get<string>("transport", "stdio");

  const serverOptions: ServerOptions =
    transport === "tcp"
      ? makeTcpServerOptions(cfg.get<string>("tcp.host", "127.0.0.1"), cfg.get<number>("tcp.port", 9999))
      : {
          command: serverPath,
          args: ["--stdio"],
          transport: TransportKind.stdio,
        };

  const clientOptions: LanguageClientOptions = {
    documentSelector: [
      { scheme: "file", language: "c" },
      { scheme: "file", language: "cpp" },
    ],
    synchronize: {
      fileEvents: workspace.createFileSystemWatcher("**/corvia.toml"),
    },
    outputChannelName: "Corvia",
  };

  client = new LanguageClient(
    "corvia",
    "Corvia",
    serverOptions,
    clientOptions,
  );

  try {
    await client.start();
  } catch (e) {
    window.showErrorMessage(
      `Failed to start corvia-lsp at '${serverPath}'. Install with \`pip install 'corvia[lsp]'\` or set corvia.serverPath in settings. (${(e as Error).message})`,
    );
  }
}

function makeTcpServerOptions(host: string, port: number): ServerOptions {
  return () => {
    return new Promise<StreamInfo>((resolve, reject) => {
      const socket = net.connect({ host, port }, () => {
        resolve({ reader: socket, writer: socket });
      });
      socket.on("error", (err) => reject(err));
    });
  };
}
