import { CSSProperties, ReactNode, useRef, useState } from "react";
import * as api from "./api";
import { AppInfo } from "./api";
import { Credentials } from "./Credentials";
import { Alert, Cpu, Download, Key, Open, Play, Refresh, Spinner, Stop, Terminal, Trash } from "./Icons";

const LABEL: Record<api.Status, string> = {
  not_installed: "Not installed", stopped: "Stopped", starting: "Starting…",
  running: "Running", error: "Error",
};

function Tool({ label, onClick, disabled, danger, children }: {
  label: string; onClick: () => void; disabled?: boolean; danger?: boolean; children: ReactNode;
}) {
  return (
    <button className={`tool ${danger ? "danger" : ""}`} aria-label={label} title={label}
            disabled={disabled} onClick={onClick}>{children}</button>
  );
}

export function Tile({ app, index, variant, manage, names, onChanged, onShowLog }: {
  app: AppInfo;
  index: number;
  variant: "card" | "hero";
  manage: boolean; // My apps shows Stop, Credentials, Update and Uninstall; the Marketplace only the main action
  names: Record<string, string>;
  onChanged: () => void;
  onShowLog: (mode: "job" | "logs") => void;
}) {
  const [busy, setBusy] = useState(false);
  const [iconOk, setIconOk] = useState(true);
  const [error, setError] = useState("");
  const [deleteData, setDeleteData] = useState(false);
  const [showCreds, setShowCreds] = useState(false);
  const [conflicts, setConflicts] = useState<string[]>([]);
  const uninstallDialog = useRef<HTMLDialogElement>(null);
  const conflictDialog = useRef<HTMLDialogElement>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
    onChanged();
  };

  const doStart = () => act(async () => {
    const found = await api.start(app.id);
    if (found) {
      setConflicts(found);
      conflictDialog.current?.showModal();
    }
  });
  const doStartAnyway = () => {
    conflictDialog.current?.close();
    act(() => api.start(app.id, true));
  };

  const doInstall = () => act(async () => { await api.install(app.id); onShowLog("job"); });
  const doUpdate = () => act(async () => { await api.update(app.id); onShowLog("job"); });
  const doUninstall = () => {
    uninstallDialog.current?.close();
    act(() => api.uninstall(app.id, deleteData));
  };

  const jobRunning = app.job?.state === "running";
  const s = app.status;
  const state = jobRunning ? "starting" : s;

  return (
    <article className={`tile ${variant} is-${state}`} style={{ "--i": index } as CSSProperties}>
      {iconOk
        ? <img className="icon" src={`/api/apps/${app.id}/icon`} alt="" onError={() => setIconOk(false)} />
        : <div className="icon letter" aria-hidden>{app.name[0]}</div>}
      <div className="tile-title">
        <p className="replaces">Instead of {app.replaces}</p>
        <h3>{app.name}</h3>
        <div className="meta">
          <span className={`pill ${state}`}>
            <i className="dot" aria-hidden />
            {jobRunning ? (app.job!.kind === "update" ? "Updating…" : "Installing…") : LABEL[s]}
          </span>
          {app.size_gb > 0 && <span className="fact">{app.size_gb} GB</span>}
          {app.gpu && <span className="fact"><Cpu /> GPU</span>}
        </div>
      </div>
      <div className="main-action">
        {jobRunning && <button className="soft" onClick={() => onShowLog("job")}><Terminal /> View log</button>}
        {!jobRunning && s === "not_installed" && (
          <button className="primary" disabled={busy} onClick={doInstall}><Download /> Install</button>
        )}
        {!jobRunning && s === "running" && (
          <a className="button primary" href={app.url} target="_blank" rel="noreferrer"><Open /> Open</a>
        )}
        {!jobRunning && s === "starting" && <button className="soft" disabled><Spinner /> Starting…</button>}
        {!jobRunning && s === "stopped" && <button className="soft" disabled={busy} onClick={doStart}><Play /> Start</button>}
        {!jobRunning && s === "error" && <button className="soft" onClick={() => onShowLog("logs")}><Terminal /> Logs</button>}
      </div>
      <p className="desc">{app.description}</p>
      {app.warnings.length > 0 && (
        <div className="badges">
          {app.warnings.map((w) => <span key={w} className="badge" title={w}><Alert /> {w}</span>)}
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {manage && !jobRunning && (
        <div className="tools">
          {(s === "running" || s === "starting" || s === "error") && (
            <Tool label="Stop" disabled={busy} onClick={() => act(() => api.stop(app.id))}><Stop /></Tool>
          )}
          {app.has_secrets && s !== "not_installed" && (
            <Tool label="Credentials" onClick={() => setShowCreds(true)}><Key /></Tool>
          )}
          {(s === "stopped" || s === "running") && (
            <Tool label="Update" disabled={busy} onClick={doUpdate}><Refresh /></Tool>
          )}
          {s !== "not_installed" && (
            <Tool label="Uninstall" danger disabled={busy}
                  onClick={() => { setDeleteData(false); uninstallDialog.current?.showModal(); }}><Trash /></Tool>
          )}
        </div>
      )}
      {jobRunning && <div className="progress" aria-hidden />}

      {showCreds && <Credentials id={app.id} name={app.name} onClose={() => setShowCreds(false)} />}

      <dialog ref={conflictDialog} className="modal small">
        <header><h2>Start {app.name}?</h2></header>
        <p className="note">
          Only one GPU app runs at a time, so this will stop {conflicts.map((c) => names[c] ?? c).join(", ")}.
        </p>
        <footer>
          <button className="ghost" onClick={() => conflictDialog.current?.close()}>Cancel</button>
          <button className="primary" onClick={doStartAnyway}>Stop and start</button>
        </footer>
      </dialog>

      <dialog ref={uninstallDialog} className="modal small">
        <header><h2>Uninstall {app.name}?</h2></header>
        <p className="note">Removes its containers and images to free disk space. Your data is kept unless you tick the box.</p>
        <label className="check">
          <input type="checkbox" checked={deleteData} onChange={(e) => setDeleteData(e.target.checked)} />
          Also delete data
        </label>
        <footer>
          <button className="ghost" onClick={() => uninstallDialog.current?.close()}>Cancel</button>
          <button className="solid-danger" onClick={doUninstall}>Uninstall</button>
        </footer>
      </dialog>
    </article>
  );
}
