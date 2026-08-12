import os from "node:os";
import path from "node:path";
import {
  DEFAULT_PORT,
  DEFAULT_TOOL_NAME,
  SERVER_NAME
} from "./constants.js";
import type { RuntimeConfig } from "./types.js";

class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

const TOOL_NAME_PATTERN = /^[A-Za-z0-9_.-]+$/;

function parsePort(raw: string | undefined): number {
  if (raw === undefined || raw.trim() === "") {
    return DEFAULT_PORT;
  }
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    throw new ConfigError(
      `Invalid PORT value "${raw}": must be a positive integer between 1 and 65535.`
    );
  }
  const value = Number.parseInt(trimmed, 10);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new ConfigError(
      `Invalid PORT value "${raw}": must be an integer between 1 and 65535.`
    );
  }
  return value;
}

function parseToolName(rawName: string | undefined, rawPrefix: string | undefined): string {
  const name = rawName === undefined || rawName.trim() === "" ? DEFAULT_TOOL_NAME : rawName.trim();
  const prefix = rawPrefix === undefined ? "" : rawPrefix.trim();

  if (!TOOL_NAME_PATTERN.test(name)) {
    throw new ConfigError(
      `Invalid TOOL_NAME value "${rawName}": only letters, digits, underscore, dot and hyphen are allowed.`
    );
  }
  if (prefix !== "" && !TOOL_NAME_PATTERN.test(prefix)) {
    throw new ConfigError(
      `Invalid TOOL_PREFIX value "${rawPrefix}": only letters, digits, underscore, dot and hyphen are allowed.`
    );
  }

  const combined = `${prefix}${name}`;
  if (combined.length > 128) {
    throw new ConfigError(
      `Invalid tool name "${combined}": combined TOOL_PREFIX and TOOL_NAME must not exceed 128 characters.`
    );
  }
  return combined;
}

function parseDataDir(raw: string | undefined): string {
  if (raw === undefined || raw.trim() === "") {
    return path.join(os.tmpdir(), `${SERVER_NAME}-data`);
  }
  const resolved = path.resolve(raw.trim());
  if (resolved === path.parse(resolved).root) {
    throw new ConfigError(
      `Invalid DATA_DIR value "${raw}": filesystem root is not an allowed data directory.`
    );
  }
  return resolved;
}

export function loadConfig(env: NodeJS.ProcessEnv): RuntimeConfig {
  const port = parsePort(env.PORT);
  const toolName = parseToolName(env.TOOL_NAME, env.TOOL_PREFIX);
  const dataDir = parseDataDir(env.DATA_DIR);
  return { port, toolName, dataDir };
}

export { ConfigError };
