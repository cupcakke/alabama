import http from "node:http";
import type { MarkdownRepository } from "./repository.js";
export interface RunningServer {
    httpServer: http.Server;
    close(): Promise<void>;
}
export declare function startHttpServer(repository: MarkdownRepository, toolName: string, port: number): Promise<RunningServer>;
