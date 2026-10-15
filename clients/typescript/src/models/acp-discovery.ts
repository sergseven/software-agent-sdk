import type { SecretObject } from './conversation';

/** One model an ACP server offers; mirrors `openhands.sdk.agent.acp_models.ACPModelInfo`. */
export interface ACPModelInfo {
  model_id: string;
  name?: string | null;
  description?: string | null;
}

/** One slash command an ACP server advertises; mirrors `openhands.sdk.agent.acp_models.ACPCommandInfo`. */
export interface ACPCommandInfo {
  /** Without the leading slash, e.g. `compact`. */
  name: string;
  description: string;
  /** Placeholder for the free-text argument, or null when there is none. */
  input_hint: string | null;
}

export interface ACPDiscoveryError {
  /** `ACPAuthRequired`, `ACPStartupTimeout`, `ACPSpawnError` or `ACPInitError`. */
  code: string;
  detail: string;
}

/** Response of `POST /api/acp/discover`; mirrors `openhands.sdk.agent.acp_models.ACPDiscovery`. */
export interface ACPDiscovery {
  agent_name: string | null;
  agent_version: string | null;
  /** The server's own default for the given credentials; may be an alias such as `default`. */
  current_model_id: string | null;
  available_models: ACPModelInfo[];
  supports_runtime_model_switch: boolean;
  /** Slash commands for a session in the request's `working_dir`. */
  available_commands: ACPCommandInfo[];
  error: ACPDiscoveryError | null;
}

export interface ACPDiscoveryRequest {
  agent_settings: {
    agent_kind: 'acp';
    acp_server: string;
    acp_command?: string[] | null;
    acp_args?: string[];
  };
  /** Same shape as a conversation start request's `secrets`. */
  secrets?: Record<string, SecretObject>;
  /** Directory to open the session in, so project-level commands are listed. */
  working_dir?: string | null;
  /** Ask the server again instead of reusing a cached result. */
  refresh?: boolean;
}

/** @deprecated Use `ACPDiscoveryError`. */
export type ACPModelDiscoveryError = ACPDiscoveryError;
/** @deprecated Use `ACPDiscovery`. */
export type ACPModelDiscovery = ACPDiscovery;
/** @deprecated Use `ACPDiscoveryRequest`. */
export type ACPModelDiscoveryRequest = ACPDiscoveryRequest;
