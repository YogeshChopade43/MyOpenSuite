export type Status = "not_installed" | "stopped" | "starting" | "running" | "error";

export interface AppInfo {
  id: string;
  name: string;
  replaces: string;
  description: string;
  gpu: boolean;
  size_gb: number;
  category: string;
  warnings: string[];
  has_secrets: boolean;
  status: Status;
  url: string;
  job: { kind: string; state: string } | null;
}

export interface JobInfo {
  kind: string;
  state: "running" | "done" | "error";
  log: string[];
}

export class RuntimeDown extends Error {}
export class Unreachable extends Error {}

async function call<T>(method: string, path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { method, headers: { "X-MOS": "1" } });
  } catch {
    throw new Unreachable("Can't reach MyOpenSuite — is the container running?");
  }
  const body = await res.json().catch(() => ({}));
  if (res.status === 503) throw new RuntimeDown(body.detail);
  if (!res.ok) {
    const err = new Error(typeof body.detail === "string" ? body.detail : res.statusText);
    (err as Error & { status: number; detail: unknown }).status = res.status;
    (err as Error & { detail: unknown }).detail = body.detail;
    throw err;
  }
  return body as T;
}

export const listApps = () => call<AppInfo[]>("GET", "/api/apps");
export const install = (id: string) => call("POST", `/api/apps/${id}/install`);
export const update = (id: string) => call("POST", `/api/apps/${id}/update`);
export const stop = (id: string) => call("POST", `/api/apps/${id}/stop`);
export const uninstall = (id: string, deleteData: boolean) =>
  call("DELETE", `/api/apps/${id}?delete_data=${deleteData}`);
export const getJob = (id: string) => call<JobInfo>("GET", `/api/apps/${id}/job`);
export interface Secret { name: string; description: string; value: string }
export const getSecrets = (id: string) => call<Secret[]>("GET", `/api/apps/${id}/secrets`);
export const getLogs =(id: string) => call<{ logs: string }>("GET", `/api/apps/${id}/logs`);

/** Start an app. Returns the GPU apps that must be stopped first, or null once started. */
export async function start(id: string, confirm = false): Promise<string[] | null> {
  try {
    await call("POST", `/api/apps/${id}/start?confirm=${confirm}`);
    return null;
  } catch (e) {
    const err = e as Error & { status?: number; detail?: { conflicts?: string[] } };
    if (err.status === 409 && err.detail?.conflicts) return err.detail.conflicts;
    throw e;
  }
}
