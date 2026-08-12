import process from "node:process";
import { ConfigError, loadConfig } from "./config.js";
import { MCP_ENDPOINT_PATH, REPOSITORY_REF, REPOSITORY_URL } from "./constants.js";
import { MarkdownRepository } from "./repository.js";
import { startHttpServer } from "./httpTransport.js";

async function main(): Promise<void> {
  let config;
  try {
    config = loadConfig(process.env);
  } catch (error) {
    if (error instanceof ConfigError) {
      process.stderr.write(`Configuration error: ${error.message}\n`);
      process.exit(1);
    }
    throw error;
  }

  const repository = new MarkdownRepository(config.dataDir);

  process.stdout.write(`Cloning ${REPOSITORY_URL} (ref ${REPOSITORY_REF}) into ${config.dataDir}\n`);
  try {
    await repository.initialize();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Failed to acquire repository content: ${message}\n`);
    process.exit(1);
  }

  const files = repository.listMarkdownFiles();
  process.stdout.write(`Indexed ${files.length} Markdown file(s):\n`);
  for (const file of files) {
    process.stdout.write(`  - ${file}\n`);
  }

  let running;
  try {
    running = await startHttpServer(repository, config.toolName, config.port);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Failed to start HTTP listener on port ${config.port}: ${message}\n`);
    process.exit(1);
  }

  process.stdout.write(
    `MCP server listening on http://0.0.0.0:${config.port}${MCP_ENDPOINT_PATH}\n`
  );
  process.stdout.write(`Tool name: ${config.toolName}\n`);

  let shuttingDown = false;
  const shutdown = async (signal: string) => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    process.stdout.write(`Received ${signal}, shutting down.\n`);
    try {
      await running.close();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write(`Error during shutdown: ${message}\n`);
      process.exit(1);
    }
    process.exit(0);
  };

  process.on("SIGINT", () => {
    void shutdown("SIGINT");
  });
  process.on("SIGTERM", () => {
    void shutdown("SIGTERM");
  });
  process.on("uncaughtException", (error) => {
    process.stderr.write(`Uncaught exception: ${error.stack ?? error.message}\n`);
    void shutdown("uncaughtException");
  });
  process.on("unhandledRejection", (reason) => {
    const message = reason instanceof Error ? (reason.stack ?? reason.message) : String(reason);
    process.stderr.write(`Unhandled rejection: ${message}\n`);
  });
}

void main();
