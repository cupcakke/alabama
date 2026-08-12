import { getAllDocuments, MarkdownDocument } from './repository.js';

export interface SearchSnippet {
  path: string;
  snippet: string;
  score: number;
}

export interface SearchResult {
  found: boolean;
  exactMatch: boolean;
  path: string | null;
  content: string | null;
  snippets: SearchSnippet[];
}

const SNIPPET_RADIUS = 180;
const MAX_SNIPPETS = 10;

function tokenize(text: string): string[] {
  const normalized = text.toLowerCase();
  const tokens: string[] = [];
  let buffer = '';
  for (let i = 0; i < normalized.length; i++) {
    const char = normalized[i];
    if ((char >= 'a' && char <= 'z') || (char >= '0' && char <= '9') || char === '_' || char === '-') {
      buffer += char;
    } else {
      if (buffer.length > 0) {
        tokens.push(buffer);
        buffer = '';
      }
    }
  }
  if (buffer.length > 0) {
    tokens.push(buffer);
  }
  return tokens;
}

function buildCorpus(docs: MarkdownDocument[]): Map<string, Map<string, number>> {
  const corpus = new Map<string, Map<string, number>>();
  for (const doc of docs) {
    const tokens = tokenize(doc.content);
    const frequencies = new Map<string, number>();
    for (const token of tokens) {
      frequencies.set(token, (frequencies.get(token) ?? 0) + 1);
    }
    corpus.set(doc.relativePath, frequencies);
  }
  return corpus;
}

function computeAverageDocLength(docs: MarkdownDocument[]): number {
  if (docs.length === 0) {
    return 0;
  }
  let total = 0;
  for (const doc of docs) {
    total += tokenize(doc.content).length;
  }
  return total / docs.length;
}

function scoreDocument(
  queryTokens: string[],
  docTokens: string[],
  frequencies: Map<string, number>,
  avgDocLength: number,
  k1: number,
  b: number
): number {
  const docLength = docTokens.length;
  let score = 0;
  for (const token of queryTokens) {
    const termFrequency = frequencies.get(token) ?? 0;
    if (termFrequency === 0) {
      continue;
    }
    const numerator = termFrequency * (k1 + 1);
    const denominator = termFrequency + k1 * (1 - b + b * (docLength / avgDocLength));
    score += numerator / denominator;
  }
  return score;
}

function extractBestSnippet(content: string, queryTokens: string[]): string {
  if (content.trim().length === 0) {
    return '';
  }
  const lowerContent = content.toLowerCase();
  const positions: Array<{ start: number; end: number }> = [];
  for (const token of queryTokens) {
    if (token.length === 0) {
      continue;
    }
    let searchFrom = 0;
    while (searchFrom <= lowerContent.length - token.length) {
      const idx = lowerContent.indexOf(token, searchFrom);
      if (idx === -1) {
        break;
      }
      positions.push({ start: idx, end: idx + token.length });
      searchFrom = idx + token.length;
    }
  }
  if (positions.length === 0) {
    return content.slice(0, SNIPPET_RADIUS * 2).trim();
  }
  let bestCenter = positions[0].start;
  let bestDensity = 0;
  for (const pos of positions) {
    let density = 0;
    for (const other of positions) {
      if (Math.abs(other.start - pos.start) <= SNIPPET_RADIUS) {
        density += 1;
      }
    }
    if (density > bestDensity) {
      bestDensity = density;
      bestCenter = pos.start;
    }
  }
  const start = Math.max(0, bestCenter - SNIPPET_RADIUS);
  const end = Math.min(content.length, bestCenter + SNIPPET_RADIUS);
  let snippet = content.slice(start, end).trim();
  if (start > 0) {
    snippet = '…' + snippet;
  }
  if (end < content.length) {
    snippet = snippet + '…';
  }
  return snippet;
}

export function readOrSearch(query: string, path?: string): SearchResult {
  const docs = getAllDocuments();
  const targetPath = path ?? query;
  const exactDoc = docs.find((doc) => doc.relativePath === targetPath);
  if (exactDoc) {
    return {
      found: true,
      exactMatch: true,
      path: exactDoc.relativePath,
      content: exactDoc.content,
      snippets: [],
    };
  }
  const queryTokens = tokenize(query);
  if (queryTokens.length === 0) {
    return { found: false, exactMatch: false, path: null, content: null, snippets: [] };
  }
  const corpus = buildCorpus(docs);
  const avgDocLength = computeAverageDocLength(docs);
  const k1 = 1.5;
  const b = 0.75;
  const snippets: SearchSnippet[] = [];
  for (const doc of docs) {
    const frequencies = corpus.get(doc.relativePath)!;
    const docTokens = tokenize(doc.content);
    const score = scoreDocument(queryTokens, docTokens, frequencies, avgDocLength, k1, b);
    if (score <= 0) {
      continue;
    }
    const snippet = extractBestSnippet(doc.content, queryTokens);
    snippets.push({ path: doc.relativePath, snippet, score });
  }
  snippets.sort((a, b) => {
    if (b.score !== a.score) {
      return b.score - a.score;
    }
    return a.path.localeCompare(b.path);
  });
  const limited = snippets.slice(0, MAX_SNIPPETS);
  return {
    found: limited.length > 0,
    exactMatch: false,
    path: null,
    content: null,
    snippets: limited,
  };
}
