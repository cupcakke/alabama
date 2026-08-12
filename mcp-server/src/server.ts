import express, { Express, NextFunction, Request, Response } from 'express';
import cors from 'cors';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createMcpServer } from './mcp.js';

export function createHttpServer(toolName: string): Express {
  const app = express();

  app.use(cors({ origin: true, methods: ['GET', 'POST', 'DELETE', 'OPTIONS'], allowedHeaders: ['Content-Type', 'Mcp-Session-Id', 'Authorization'] }));
  app.use(express.json({ limit: '16mb' }));

  app.options('/mcp', (_req: Request, res: Response) => {
    res.status(204).end();
  });

  app.post('/mcp', async (req: Request, res: Response) => {
    try {
      const server = createMcpServer(toolName);
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true,
      });
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
      res.on('close', () => {
        transport.close();
        server.close();
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: {
            code: -32603,
            message: `Internal server error: ${message}`,
          },
          id: null,
        });
      }
    }
  });

  app.get('/mcp', (_req: Request, res: Response) => {
    res.status(405).json({
      jsonrpc: '2.0',
      error: {
        code: -32000,
        message: 'Method not allowed. Use POST to send JSON-RPC requests.',
      },
      id: null,
    });
  });

  app.delete('/mcp', (_req: Request, res: Response) => {
    res.status(405).json({
      jsonrpc: '2.0',
      error: {
        code: -32000,
        message: 'Method not allowed. Use POST to send JSON-RPC requests.',
      },
      id: null,
    });
  });

  app.use((_req: Request, res: Response) => {
    res.status(404).json({
      jsonrpc: '2.0',
      error: {
        code: -32000,
        message: 'Not found.',
      },
      id: null,
    });
  });

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
    const message = err instanceof Error ? err.message : String(err);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: '2.0',
        error: {
          code: -32603,
          message: `Internal server error: ${message}`,
        },
        id: null,
      });
    }
  });

  return app;
}
