import { useRef, useState } from "react";
import * as api from "./api";
import { AppInfo } from "./api";
import { Credentials } from "./Credentials";

const LABEL: Record<api.Status, string> = {
  not_installed: "Not installed", stopped: "Stopped", starting: "Starting…",
  running: "Running", error: "Error",
};

export function Tile({ app, names, onChanged, onShowLog }: {
  app: AppInfo;
  names: Record<string, string>;
  onChanged: () => void;
  onShowLog: (mode: "job" | "logs") => void;
}) {
  const [busy, setBusy] = useState(false);
  const [iconOk, setIconOk] = useState(true);
  const [error, setError] = useState("");
  const [deleteData, setDeleteData] = useState(false);
  const [showCreds, setShowCreds] = useState(false);
  const uninstallDialog = useRef<HTMLDialogElement>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
    onChanged();
  };

  const doStart = () => act(async () => {
    const conflicts = await api.start(app.id);
    if (conflicts && window.confirm(`This will stop ${conflicts.map((c) => names[c] ?? c).join(", ")}. Continue?`)) {
      await api.start(app.id, true);
    }
  });

  const doInstall = () => act(async () => { await api.install(app.id); onShowLog("job"); });
  const doUpdate = () => act(async () => { await api.update(app.id); onShowLog("job"); });
  const doUninstall = () => {
    uninstallDialog.current?.close();
    act(() => api.uninstall(app.id, deleteData));
  };

  const jobRunning = app.job?.state === "running";
  const s = app.status;

  return (
    <article className="tile">
      <div className="tile-head">
        {iconOk
          ? <img className="icon" src={`/api/apps/${app.id}/icon`} alt="" onError={() => setIconOk(false)} />
          : <div className="icon letter" aria-hidden>{app.name[0]}</div>}
        <div>
          <h3>{app.name}</h3>
          <p className="replaces">Replaces {app.replaces}</p>
        </div>
      </div>
      <p className="desc">{app.description}</p>
      <div className="badges">
        <span className={`pill ${jobRunning ? "starting" : s}`}>
          {jobRunning ? (app.job!.kind === "update" ? "Updating…" : "Installing…") : LABEL[s]}
        </span>
        {app.gpu && <span className="badge">GPU</span>}
        {app.warnings.map((w) => <span key={w} className="badge warn" title={w}>⚠ {w}</span>)}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        {jobRunning ? (
          <button onClick={() => onShowLog("job")}>View log</button>
        ) : (
          <>
            {s === "not_installed" && (
              <button disabled={busy} onClick={doInstall}>
                Install{app.size_gb ? ` · ~${app.size_gb} GB` : ""}
              </button>
            )}
            {s === "running" && <a className="button" href={app.url} target="_blank" rel="noreferrer">Open</a>}
            {s === "starting" && <button disabled>Starting…</button>}
            {s === "stopped" && <button disabled={busy} onClick={doStart}>Start</button>}
            {(s === "running" || s === "starting" || s === "error") && (
              <button className="ghost" disabled={busy} onClick={() => act(() => api.stop(app.id))}>Stop</button>
            )}
            {s === "error" && <button className="ghost" onClick={() => onShowLog("logs")}>Logs</button>}
            {app.has_secrets && s !== "not_installed" && (
              <button className="ghost" onClick={() => setShowCreds(true)}>Credentials</button>
            )}
            {(s === "stopped" || s === "running") && <button className="ghost" disabled={busy} onClick={doUpdate}>Update</button>}
            {s !== "not_installed" && (
              <button className="ghost danger" disabled={busy} onClick={() => { setDeleteData(false); uninstallDialog.current?.showModal(); }}>
                Uninstall
              </button>
            )}
          </>
        )}
      </div>

      {showCreds && <Credentials id={app.id} name={app.name} onClose={() => setShowCreds(false)} />}

      <dialog ref={uninstallDialog} className="modal small">
        <header><h2>Uninstall {app.name}?</h2></header>
        <p className="note">Removes its containers and images to free disk space. Your data is kept unless you tick the box.</p>
        <label className="check">
          <input type="checkbox" checked={deleteData} onChange={(e) => setDeleteData(e.target.checked)} />
          Also delete data
        </label>
        <footer>
          <button className="danger" onClick={doUninstall}>Uninstall</button>
          <button className="ghost" onClick={() => uninstallDialog.current?.close()}>Cancel</button>
        </footer>
      </dialog>
    </article>
  );
}
