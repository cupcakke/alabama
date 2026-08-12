import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { tmpdir } from 'node:os';
import { REPO_URL, REPO_REF, FILE_EXTENSION } from './config.js';

export interface MarkdownDocument {
  relativePath: string;
  content: string;
}

let documents: MarkdownDocument[] = [];
let dataDirectory: string = '';

function runGit(args: string[], cwd: string): { stdout: string; stderr: string; status: number } {
  const result = spawnSync('git', args, { cwd, encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024 });
  return { stdout: result.stdout ?? '', stderr: result.stderr ?? '', status: result.status ?? -1 };
}

export function cloneRepository(targetDir?: string): string {
  const dest = targetDir ?? join(tmpdir(), `alabama-mcp-${process.pid}-${Date.now()}`);
  if (existsSync(dest)) {
    rmSync(dest, { recursive: true, force: true });
  }
  mkdirSync(dest, { recursive: true });

  const cloneResult = runGit(['clone', '--depth', '1', '--branch', REPO_REF, '--single-branch', REPO_URL, dest], process.cwd());
  if (cloneResult.status !== 0) {
    throw new Error(`Failed to clone repository: ${cloneResult.stderr || cloneResult.stdout}`);
  }
  const gitDir = join(dest, '.git');
  if (existsSync(gitDir)) {
    rmSync(gitDir, { recursive: true, force: true });
  }
  dataDirectory = dest;
  return dest;
}

export function indexMarkdownFiles(repoDir: string): MarkdownDocument[] {
  const docs: MarkdownDocument[] = [];
  const root = repoDir;
  const walk = (currentDir: string): void => {
    const entries = readdirSync(currentDir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = join(currentDir, entry.name);
      if (entry.isDirectory()) {
        walk(fullPath);
      } else if (entry.isFile() && entry.name.endsWith(FILE_EXTENSION)) {
        const fileStat = statSync(fullPath);
        if (!fileStat.isFile()) {
          continue;
        }
        const content = readFileSync(fullPath, 'utf-8');
        const relPath = relative(root, fullPath).split('/').join('/');
        docs.push({ relativePath: relPath, content });
      }
    }
  };
  walk(root);
  docs.sort((a, b) => a.relativePath.localeCompare(b.relativePath));
  documents = docs;
  return docs;
}

export function listMarkdownFiles(): string[] {
  return documents.map((doc) => doc.relativePath);
}

export function getAllDocuments(): MarkdownDocument[] {
  return documents;
}

export function getDataDirectory(): string {
  return dataDirectory;
}
