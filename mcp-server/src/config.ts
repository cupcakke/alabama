export const REPO_URL = 'https://github.com/cupcakke/alabama.git';
export const REPO_REF = 'main';
export const FILE_EXTENSION = '.md';

export interface AppConfig {
  port: number;
  toolName: string;
  toolPrefix: string;
  resolvedToolName: string;
}

function parsePort(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === '') {
    return fallback;
  }
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    console.error(`Invalid PORT value: "${raw}". PORT must be a positive integer.`);
    process.exit(1);
  }
  const value = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(value) || value < 1 || value > 65535) {
    console.error(`Invalid PORT value: "${raw}". PORT must be an integer between 1 and 65535.`);
    process.exit(1);
  }
  return value;
}

function parseToolName(raw: string | undefined, fallback: string): string {
  if (raw === undefined || raw === '') {
    return fallback;
  }
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return fallback;
  }
  if (!/^[a-zA-Z][a-zA-Z0-9_-]{0,127}$/.test(trimmed)) {
    console.error(`Invalid TOOL_NAME value: "${raw}". TOOL_NAME must start with a letter and contain only letters, digits, underscores, and hyphens.`);
    process.exit(1);
  }
  return trimmed;
}

function parseToolPrefix(raw: string | undefined): string {
  if (raw === undefined || raw === '') {
    return '';
  }
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return '';
  }
  if (!/^[a-zA-Z][a-zA-Z0-9_-]{0,127}$/.test(trimmed)) {
    console.error(`Invalid TOOL_PREFIX value: "${raw}". TOOL_PREFIX must start with a letter and contain only letters, digits, underscores, and hyphens.`);
    process.exit(1);
  }
  return trimmed;
}

export function loadConfig(): AppConfig {
  const port = parsePort(process.env.PORT, 8080);
  const toolName = parseToolName(process.env.TOOL_NAME, 'search_alabama_md');
  const toolPrefix = parseToolPrefix(process.env.TOOL_PREFIX);
  const resolvedToolName = `${toolPrefix}${toolName}`;
  return { port, toolName, toolPrefix, resolvedToolName };
}
