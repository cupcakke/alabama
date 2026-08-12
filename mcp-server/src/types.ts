export interface RuntimeConfig {
  port: number;
  toolName: string;
  dataDir: string;
}

export interface MarkdownFile {
  path: string;
  content: string;
  lowerContent: string;
  lowerPath: string;
  lines: string[];
}

export interface SnippetMatch {
  path: string;
  score: number;
  line: number;
  snippet: string;
}

export interface SearchOutcome {
  kind: "file" | "snippets" | "empty";
  path?: string;
  content?: string;
  matches?: SnippetMatch[];
  query: string;
  totalFiles: number;
}
