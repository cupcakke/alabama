import type { SearchOutcome } from "./types.js";
export declare class MarkdownRepository {
    private readonly dataDir;
    private readonly checkoutDir;
    private files;
    private index;
    constructor(dataDir: string);
    initialize(): Promise<void>;
    private clone;
    private indexMarkdownFiles;
    private walk;
    listMarkdownFiles(): string[];
    fileCount(): number;
    private resolveFile;
    private tokenize;
    private buildSnippet;
    private searchSnippets;
    readOrSearch(query: string, filePath?: string): SearchOutcome;
}
