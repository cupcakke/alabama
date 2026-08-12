import type { RuntimeConfig } from "./types.js";
declare class ConfigError extends Error {
    constructor(message: string);
}
export declare function loadConfig(env: NodeJS.ProcessEnv): RuntimeConfig;
export { ConfigError };
