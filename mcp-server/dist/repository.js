import fs from "node:fs/promises";
import path from "node:path";
import { simpleGit } from "simple-git";
import { MARKDOWN_EXTENSION, MAX_SNIPPET_RESULTS, REPOSITORY_REF, REPOSITORY_URL, SNIPPET_CONTEXT_CHARS } from "./constants.js";
const IGNORED_DIRECTORIES = new Set([".git"]);
export class MarkdownRepository {
    dataDir;
    checkoutDir;
    files = [];
    index = new Map();
    constructor(dataDir) {
        this.dataDir = dataDir;
        this.checkoutDir = path.join(dataDir, "alabama");
    }
    async initialize() {
        await this.clone();
        await this.indexMarkdownFiles();
    }
    async clone() {
        await fs.rm(this.checkoutDir, { recursive: true, force: true });
        await fs.mkdir(this.dataDir, { recursive: true });
        const git = simpleGit({ baseDir: this.dataDir });
        await git.clone(REPOSITORY_URL, this.checkoutDir, [
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            REPOSITORY_REF
        ]);
    }
    async indexMarkdownFiles() {
        const collected = [];
        await this.walk(this.checkoutDir, collected);
        collected.sort((a, b) => a.path.localeCompare(b.path));
        this.files = collected;
        this.index = new Map();
        for (const file of collected) {
            this.index.set(file.path, file);
            this.index.set(file.path.toLowerCase(), file);
            this.index.set(`./${file.path}`, file);
            this.index.set(`/${file.path}`, file);
        }
    }
    async walk(directory, out) {
        const entries = await fs.readdir(directory, { withFileTypes: true });
        for (const entry of entries) {
            const absolute = path.join(directory, entry.name);
            if (entry.isDirectory()) {
                if (IGNORED_DIRECTORIES.has(entry.name)) {
                    continue;
                }
                await this.walk(absolute, out);
                continue;
            }
            if (!entry.isFile()) {
                continue;
            }
            if (!entry.name.toLowerCase().endsWith(MARKDOWN_EXTENSION)) {
                continue;
            }
            const content = await fs.readFile(absolute, "utf8");
            const relative = path.relative(this.checkoutDir, absolute).split(path.sep).join("/");
            out.push({
                path: relative,
                content,
                lowerContent: content.toLowerCase(),
                lowerPath: relative.toLowerCase(),
                lines: content.split(/\r?\n/)
            });
        }
    }
    listMarkdownFiles() {
        return this.files.map((file) => file.path);
    }
    fileCount() {
        return this.files.length;
    }
    resolveFile(query) {
        const trimmed = query.trim();
        if (trimmed === "") {
            return undefined;
        }
        const normalized = trimmed.split(path.sep).join("/").replace(/^\.\//, "").replace(/^\/+/, "");
        const direct = this.index.get(trimmed) ??
            this.index.get(normalized) ??
            this.index.get(normalized.toLowerCase());
        if (direct) {
            return direct;
        }
        const basenameMatches = this.files.filter((file) => file.path.toLowerCase() === normalized.toLowerCase());
        if (basenameMatches.length === 1) {
            return basenameMatches[0];
        }
        return undefined;
    }
    tokenize(query) {
        return query
            .toLowerCase()
            .split(/[^\p{L}\p{N}_]+/u)
            .filter((token) => token.length > 0);
    }
    buildSnippet(file, position) {
        const start = Math.max(0, position - Math.floor(SNIPPET_CONTEXT_CHARS / 2));
        const end = Math.min(file.content.length, start + SNIPPET_CONTEXT_CHARS);
        const raw = file.content.slice(start, end);
        const prefix = start > 0 ? "..." : "";
        const suffix = end < file.content.length ? "..." : "";
        const lineNumber = file.content.slice(0, position).split(/\r?\n/).length;
        const snippet = `${prefix}${raw.replace(/\s+/g, " ").trim()}${suffix}`;
        return { line: lineNumber, snippet };
    }
    searchSnippets(query) {
        const tokens = this.tokenize(query);
        const phrase = query.trim().toLowerCase();
        const results = [];
        for (const file of this.files) {
            let score = 0;
            let bestPosition = -1;
            if (phrase.length > 0) {
                let searchFrom = 0;
                let occurrences = 0;
                for (;;) {
                    const found = file.lowerContent.indexOf(phrase, searchFrom);
                    if (found === -1) {
                        break;
                    }
                    occurrences += 1;
                    if (bestPosition === -1) {
                        bestPosition = found;
                    }
                    searchFrom = found + phrase.length;
                    if (occurrences > 500) {
                        break;
                    }
                }
                if (occurrences > 0) {
                    score += occurrences * 12;
                }
                if (file.lowerPath.includes(phrase)) {
                    score += 40;
                }
            }
            for (const token of tokens) {
                let searchFrom = 0;
                let occurrences = 0;
                for (;;) {
                    const found = file.lowerContent.indexOf(token, searchFrom);
                    if (found === -1) {
                        break;
                    }
                    occurrences += 1;
                    if (bestPosition === -1) {
                        bestPosition = found;
                    }
                    searchFrom = found + token.length;
                    if (occurrences > 1000) {
                        break;
                    }
                }
                if (occurrences > 0) {
                    score += occurrences * 3 + 5;
                }
                if (file.lowerPath.includes(token)) {
                    score += 15;
                }
            }
            if (score <= 0) {
                continue;
            }
            const position = bestPosition === -1 ? 0 : bestPosition;
            const { line, snippet } = this.buildSnippet(file, position);
            results.push({ path: file.path, score, line, snippet });
        }
        results.sort((a, b) => {
            if (b.score !== a.score) {
                return b.score - a.score;
            }
            return a.path.localeCompare(b.path);
        });
        return results.slice(0, MAX_SNIPPET_RESULTS);
    }
    readOrSearch(query, filePath) {
        const totalFiles = this.files.length;
        if (filePath !== undefined && filePath.trim() !== "") {
            const explicit = this.resolveFile(filePath);
            if (explicit) {
                return {
                    kind: "file",
                    path: explicit.path,
                    content: explicit.content,
                    query,
                    totalFiles
                };
            }
        }
        const exact = this.resolveFile(query);
        if (exact) {
            return {
                kind: "file",
                path: exact.path,
                content: exact.content,
                query,
                totalFiles
            };
        }
        const matches = this.searchSnippets(query);
        if (matches.length === 0) {
            return { kind: "empty", matches: [], query, totalFiles };
        }
        return { kind: "snippets", matches, query, totalFiles };
    }
}
