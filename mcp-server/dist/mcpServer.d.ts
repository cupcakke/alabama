import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import type { MarkdownRepository } from "./repository.js";
export declare function createMcpServer(repository: MarkdownRepository, toolName: string): Server;
