import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { REPOSITORY_REF, REPOSITORY_URL, SERVER_NAME, SERVER_VERSION } from "./constants.js";
function renderOutcome(outcome, repository) {
    if (outcome.kind === "file") {
        return [
            `# File: ${outcome.path}`,
            `Repository: ${REPOSITORY_URL} (ref: ${REPOSITORY_REF})`,
            "",
            outcome.content ?? ""
        ].join("\n");
    }
    if (outcome.kind === "snippets") {
        const header = [
            `# Search results for: ${outcome.query}`,
            `Repository: ${REPOSITORY_URL} (ref: ${REPOSITORY_REF})`,
            `Markdown files indexed: ${outcome.totalFiles}`,
            `Matches returned: ${outcome.matches?.length ?? 0}`,
            ""
        ];
        const body = (outcome.matches ?? []).map((match, position) => {
            return [
                `## ${position + 1}. ${match.path} (line ${match.line}, score ${match.score})`,
                match.snippet,
                ""
            ].join("\n");
        });
        const footer = [
            "---",
            "Pass an exact relative path as the query to retrieve the complete Markdown source.",
            ""
        ];
        return [...header, ...body, ...footer].join("\n");
    }
    const available = repository.listMarkdownFiles();
    return [
        `# No matches for: ${outcome.query}`,
        `Repository: ${REPOSITORY_URL} (ref: ${REPOSITORY_REF})`,
        `Markdown files indexed: ${outcome.totalFiles}`,
        "",
        "## Available Markdown files",
        ...available.map((entry) => `- ${entry}`),
        ""
    ].join("\n");
}
export function createMcpServer(repository, toolName) {
    const server = new Server({
        name: SERVER_NAME,
        version: SERVER_VERSION
    }, {
        capabilities: {
            tools: {}
        },
        instructions: `This server exposes exclusively the Markdown files of ${REPOSITORY_URL} (ref ${REPOSITORY_REF}). Call the "${toolName}" tool with an exact relative .md path to obtain the complete file content, or with free text to obtain ranked snippets from all Markdown files.`
    });
    server.setRequestHandler(ListToolsRequestSchema, async () => {
        const files = repository.listMarkdownFiles();
        return {
            tools: [
                {
                    name: toolName,
                    title: "Alabama Markdown reader and search",
                    description: [
                        `Read or search the Markdown files of ${REPOSITORY_URL} (ref ${REPOSITORY_REF}).`,
                        "If the query exactly matches a relative .md path, the full untruncated Markdown source of that file is returned.",
                        "Otherwise the query is treated as free text and ranked snippets from all Markdown files are returned together with their paths.",
                        `Indexed Markdown files (${files.length}): ${files.join(", ")}`
                    ].join(" "),
                    inputSchema: {
                        type: "object",
                        properties: {
                            query: {
                                type: "string",
                                description: "An exact relative path of a Markdown file inside the repository to read its complete content, or free text to search across all Markdown files."
                            }
                        },
                        required: ["query"],
                        additionalProperties: false
                    }
                }
            ]
        };
    });
    server.setRequestHandler(CallToolRequestSchema, async (request) => {
        const requestedName = request.params.name;
        if (requestedName !== toolName) {
            return {
                isError: true,
                content: [
                    {
                        type: "text",
                        text: `Unknown tool "${requestedName}". The only available tool is "${toolName}".`
                    }
                ]
            };
        }
        const args = request.params.arguments;
        const rawQuery = args && typeof args === "object" && "query" in args
            ? args.query
            : undefined;
        if (typeof rawQuery !== "string" || rawQuery.trim() === "") {
            return {
                isError: true,
                content: [
                    {
                        type: "text",
                        text: 'Invalid arguments: "query" must be a non-empty string containing either an exact relative .md path or free search text.'
                    }
                ]
            };
        }
        try {
            const outcome = repository.readOrSearch(rawQuery);
            return {
                content: [
                    {
                        type: "text",
                        text: renderOutcome(outcome, repository)
                    }
                ],
                isError: false
            };
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            return {
                isError: true,
                content: [
                    {
                        type: "text",
                        text: `Internal error while processing the query: ${message}`
                    }
                ]
            };
        }
    });
    return server;
}
