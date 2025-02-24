// Determine the API base URL
// If NEXT_PUBLIC_API_BASE is set, use it
// Otherwise, use the current origin (for same-domain deployments)
const getApiBase = () => {
  if (process.env.NEXT_PUBLIC_API_BASE) {
    return process.env.NEXT_PUBLIC_API_BASE;
  }

  // When running in the browser, use the current origin
  if (typeof window !== "undefined") {
    return window.location.origin;
  }

  // Default to empty string (relative URLs) during SSR
  return "";
};

const API_BASE = getApiBase();

export interface ServerMode {
  is_disabled: boolean;
  dry_run: boolean;
}

export interface ServerState {
  mode: ServerMode;
  repositories: number;
  recent_suggestions: number;
}

export interface Suggestion {
  id: string;
  repository: string;
  pr_number: number;
  file_path: string;
  timestamp: string;
  status: "pending" | "accepted" | "rejected" | "applied" | "dry_run";
  suggestion_text: string;
  comment_url?: string;
  is_dry_run: boolean;
  dry_run_preview?: {
    thread_root_id: string;
    content: string;
    rule_generation: any;
  };
}

export interface Repository {
  full_name: string;
  installation_id: number;
  connected_at: string;
  last_active: string;
  enabled: boolean;
}

export interface SetupStatus {
  configured: boolean;
  variables: {
    LLM_API_KEY: boolean;
    GITHUB_APP_ID: boolean;
    GITHUB_PRIVATE_KEY: boolean;
    WEBHOOK_SECRET: boolean;
  };
  setup_complete: boolean;
}

export async function getServerState(): Promise<ServerState> {
  const response = await fetch(`${API_BASE}/api/state`);
  if (!response.ok) {
    throw new Error("Failed to fetch server state");
  }
  return response.json();
}

export async function getSuggestions(
  repository?: string
): Promise<{ suggestions: Suggestion[] }> {
  const url = new URL(`${API_BASE}/api/suggestions`);
  if (repository) {
    url.searchParams.set("repository", repository);
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error("Failed to fetch suggestions");
  }
  return response.json();
}

export async function getRepositories(): Promise<{
  repositories: Repository[];
}> {
  const response = await fetch(`${API_BASE}/api/repositories`);
  if (!response.ok) {
    throw new Error("Failed to fetch repositories");
  }
  return response.json();
}

export async function updateServerMode(
  mode: Partial<ServerMode>
): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/api/mode`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(mode),
  });
  if (!response.ok) {
    throw new Error("Failed to update server mode");
  }
  return response.json();
}

export async function updateRepository(
  full_name: string,
  enabled: boolean
): Promise<{ message: string }> {
  // Split and encode each part of the path separately
  const encodedPath = full_name
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  const response = await fetch(`${API_BASE}/api/repositories/${encodedPath}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) {
    throw new Error("Failed to update repository");
  }
  return response.json();
}

export async function getSetupStatus(): Promise<SetupStatus> {
  const response = await fetch(`${API_BASE}/api/setup-status`);
  if (!response.ok) {
    throw new Error(`Failed to get setup status: ${response.statusText}`);
  }
  return response.json();
}
