import http from "node:http";
import express from "express";
import cors from "cors";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { MCP_ENDPOINT_PATH, SERVER_NAME, SERVER_VERSION } from "./constants.js";
import { createMcpServer } from "./mcpServer.js";
function jsonRpcError(res, status, code, message, id) {
    if (res.headersSent) {
        return;
    }
    res.status(status).json({
        jsonrpc: "2.0",
        error: { code, message },
        id: id === undefined ? null : id
    });
}
export async function startHttpServer(repository, toolName, port) {
    const app = express();
    app.use(cors({
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
    }));
    app.use(express.json({ limit: "8mb" }));
    app.use((error, _req, res, next) => {
        if (error instanceof SyntaxError) {
            jsonRpcError(res, 400, -32700, "Parse error: request body is not valid JSON.", null);
            return;
        }
        next(error);
    });
    app.options(MCP_ENDPOINT_PATH, (_req, res) => {
        res.status(204).end();
    });
    app.post(MCP_ENDPOINT_PATH, async (req, res) => {
        const requestId = req.body && typeof req.body === "object" && !Array.isArray(req.body)
            ? req.body.id
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
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            jsonRpcError(res, 500, -32603, `Internal error: ${message}`, requestId);
            await transport.close().catch(() => undefined);
            await server.close().catch(() => undefined);
        }
    });
    app.get(MCP_ENDPOINT_PATH, (_req, res) => {
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
    app.delete(MCP_ENDPOINT_PATH, (_req, res) => {
        res.status(204).end();
    });
    app.get("/", (_req, res) => {
        res.status(200).json({
            name: SERVER_NAME,
            version: SERVER_VERSION,
            endpoint: MCP_ENDPOINT_PATH,
            transport: "streamable-http",
            tool: toolName,
            markdownFiles: repository.fileCount()
        });
    });
    app.use((_req, res) => {
        jsonRpcError(res, 404, -32601, `Not found: the MCP endpoint is ${MCP_ENDPOINT_PATH}.`, null);
    });
    app.use((error, _req, res, _next) => {
        const message = error instanceof Error ? error.message : String(error);
        jsonRpcError(res, 500, -32603, `Internal error: ${message}`, null);
    });
    const httpServer = http.createServer(app);
    await new Promise((resolve, reject) => {
        const onError = (error) => {
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
        close: () => new Promise((resolve, reject) => {
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
