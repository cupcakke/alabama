import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { readOrSearch } from './search.js';

export function createMcpServer(toolName: string): McpServer {
  const server = new McpServer(
    {
      name: 'alabama-md-mcp',
      version: '1.0.0',
    },
    { capabilities: { tools: {} } }
  );

  server.registerTool(
    toolName,
    {
      description:
        'Retrieve the full content of a Markdown file from the alabama repository by its exact relative path, or search across all Markdown files using free-text queries to get ranked snippets.',
      inputSchema: {
        query: z
          .string()
          .describe(
            'Either the exact relative path of a .md file (e.g. "README.md") to retrieve its full content, or a free-text query to search across all Markdown files.'
          ),
      },
    },
    async (args: unknown) => {
      const params = args as { query: string };
      const query = params.query;
      if (typeof query !== 'string' || query.trim().length === 0) {
        return {
          content: [
            {
              type: 'text' as const,
              text: 'Error: "query" must be a non-empty string.',
            },
          ],
          isError: true,
        };
      }
      const result = readOrSearch(query.trim());
      if (result.exactMatch && result.content !== null) {
        return {
          content: [
            {
              type: 'text' as const,
              text: JSON.stringify(
                {
                  match_type: 'exact_path',
                  path: result.path,
                  content: result.content,
                },
                null,
                2
              ),
            },
          ],
        };
      }
      if (!result.found || result.snippets.length === 0) {
        return {
          content: [
            {
              type: 'text' as const,
              text: JSON.stringify(
                {
                  match_type: 'search',
                  query: query.trim(),
                  results_count: 0,
                  results: [],
                },
                null,
                2
              ),
            },
          ],
        };
      }
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify(
              {
                match_type: 'search',
                query: query.trim(),
                results_count: result.snippets.length,
                results: result.snippets.map((snippet) => ({
                  path: snippet.path,
                  score: Number(snippet.score.toFixed(4)),
                  snippet: snippet.snippet,
                })),
              },
              null,
              2
            ),
          },
        ],
      };
    }
  );

  return server;
}
