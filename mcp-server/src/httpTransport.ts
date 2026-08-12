import http from "node:http";
import express from "express";
import type { Request, Response } from "express";
import cors from "cors";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { MCP_ENDPOINT_PATH, SERVER_NAME, SERVER_VERSION } from "./constants.js";
import { createMcpServer } from "./mcpServer.js";
import type { MarkdownRepository } from "./repository.js";

export interface RunningServer {
  httpServer: http.Server;
  close(): Promise<void>;
}

function jsonRpcError(res: Response, status: number, code: number, message: string, id: unknown): void {
  if (res.headersSent) {
    return;
  }
  res.status(status).json({
    jsonrpc: "2.0",
    error: { code, message },
    id: id === undefined ? null : id
  });
}

export async function startHttpServer(
  repository: MarkdownRepository,
  toolName: string,
  port: number
): Promise<RunningServer> {
  const app = express();

  app.use(
    cors({
      origin: "*",
      methods: ["GET", "POST", "DELETE", "OPTIONS"],
      allowedHeaders: [
        "Content-Type",
        "Accept",
        "Mcp-Session-Id",
        "Last-Event-ID",
        "MCP-Protocol-Version",
        "Authorization"
      ],
      exposedHeaders: ["Mcp-Session-Id", "WWW-Authenticate"],
      credentials: false,
      maxAge: 86400
    })
  );

  app.use(express.json({ limit: "8mb" }));

  app.use((error: unknown, _req: Request, res: Response, next: express.NextFunction) => {
    if (error instanceof SyntaxError) {
      jsonRpcError(res, 400, -32700, "Parse error: request body is not valid JSON.", null);
      return;
    }
    next(error);
  });

  app.options(MCP_ENDPOINT_PATH, (_req: Request, res: Response) => {
    res.status(204).end();
  });

  app.post(MCP_ENDPOINT_PATH, async (req: Request, res: Response) => {
    const requestId =
      req.body && typeof req.body === "object" && !Array.isArray(req.body)
        ? (req.body as Record<string, unknown>).id
        : null;

    if (req.body === undefined || req.body === null) {
      jsonRpcError(res, 400, -32600, "Invalid Request: missing JSON-RPC body.", requestId);
      return;
    }

    const server = createMcpServer(repository, toolName);
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true
    });

    res.on("close", () => {
      void transport.close();
      void server.close();
    });

    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      jsonRpcError(res, 500, -32603, `Internal error: ${message}`, requestId);
      await transport.close().catch(() => undefined);
      await server.close().catch(() => undefined);
    }
  });

  app.get(MCP_ENDPOINT_PATH, (_req: Request, res: Response) => {
    res
      .status(405)
      .set("Allow", "POST, OPTIONS")
      .json({
        jsonrpc: "2.0",
        error: {
          code: -32000,
          message: "Method not allowed: use HTTP POST with a JSON-RPC body on this endpoint."
        },
        id: null
      });
  });

  app.delete(MCP_ENDPOINT_PATH, (_req: Request, res: Response) => {
    res.status(204).end();
  });

  app.get("/", (_req: Request, res: Response) => {
    res.status(200).json({
      name: SERVER_NAME,
      version: SERVER_VERSION,
      endpoint: MCP_ENDPOINT_PATH,
      transport: "streamable-http",
      tool: toolName,
      markdownFiles: repository.fileCount()
    });
  });

  app.use((_req: Request, res: Response) => {
    jsonRpcError(res, 404, -32601, `Not found: the MCP endpoint is ${MCP_ENDPOINT_PATH}.`, null);
  });

  app.use((error: unknown, _req: Request, res: Response, _next: express.NextFunction) => {
    const message = error instanceof Error ? error.message : String(error);
    jsonRpcError(res, 500, -32603, `Internal error: ${message}`, null);
  });

  const httpServer = http.createServer(app);

  await new Promise<void>((resolve, reject) => {
    const onError = (error: Error) => {
      httpServer.removeListener("error", onError);
      reject(error);
    };
    httpServer.once("error", onError);
    httpServer.listen(port, "0.0.0.0", () => {
      httpServer.removeListener("error", onError);
      resolve();
    });
  });

  return {
    httpServer,
    close: () =>
      new Promise<void>((resolve, reject) => {
        httpServer.close((error) => {
          if (error) {
            reject(error);
            return;
          }
          resolve();
        });
        httpServer.closeAllConnections();
      })
  };
}
