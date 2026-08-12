import { createHttpServer } from './server.js';
import { cloneRepository, indexMarkdownFiles, listMarkdownFiles } from './repository.js';
import { loadConfig } from './config.js';

async function main(): Promise<void> {
  const config = loadConfig();

  console.log(`Cloning repository ${'https://github.com/cupcakke/alabama.git'} (ref: ${'main'})...`);
  const repoDir = cloneRepository();
  console.log(`Repository cloned to: ${repoDir}`);

  const documents = indexMarkdownFiles(repoDir);
  const paths = listMarkdownFiles();
  console.log(`Indexed ${documents.length} Markdown files.`);

  const app = createHttpServer(config.resolvedToolName);
  const server = app.listen(config.port, () => {
    console.log(`MCP server listening on http://0.0.0.0:${config.port}/mcp`);
    console.log(`Tool name: ${config.resolvedToolName}`);
    console.log(`Available Markdown files: ${paths.length}`);
  });

  const shutdown = (signal: string) => {
    console.log(`Received ${signal}, shutting down...`);
    server.close(() => {
      process.exit(0);
    });
    setTimeout(() => {
      process.exit(1);
    }, 10000).unref();
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

main().catch((error) => {
  console.error('Fatal error during startup:', error);
  process.exit(1);
});
