import { FormEvent, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { ImportPreview } from "./api";
import { Alert, Spinner } from "./Icons";

/** Paste a GitHub link, review what was found, then add and install it. */
export function ImportDialog({ onClose, onImported }: { onClose: () => void; onImported: (id: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [url, setUrl] = useState("");
  const [replaces, setReplaces] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { dialog.current?.showModal(); }, []);

  const check = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setPreview(null);
    try { setPreview(await api.previewImport(url)); } catch (err) { setError((err as Error).message); }
    setBusy(false);
  };

  const add = async () => {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const { id } = await api.importApp(url, preview.sha, replaces);
      await api.install(id);
      onImported(id);
      dialog.current?.close();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  const blocked = (preview?.blockers.length ?? 0) > 0;
  return (
    <dialog ref={dialog} className="modal import" onClose={onClose}>
      <header><h2>Import from GitHub</h2></header>
      <form className="import-form" onSubmit={check}>
        <label htmlFor="import-url">GitHub link</label>
        <div className="secret-row">
          <input id="import-url" type="url" required autoFocus placeholder="https://github.com/owner/repo"
                 value={url} onChange={(e) => { setUrl(e.target.value); setPreview(null); }} />
          <button className="primary" disabled={busy}>{busy && !preview ? <Spinner /> : null} Check</button>
        </div>
      </form>
      {error && <p className="error note" role="alert">{error}</p>}
      {preview && (
        <div className="review">
          <h3>{preview.name}</h3>
          <p className="note">{preview.description}</p>
          <dl>
            <dt>Stars</dt><dd>{preview.stars.toLocaleString()}</dd>
            <dt>Licence</dt><dd>{preview.license}</dd>
            {!blocked && <><dt>Runs from</dt><dd>{preview.build ? "Built from source" : preview.image}</dd></>}
            {!blocked && <><dt>Opens at</dt><dd>localhost:{preview.port}</dd></>}
          </dl>
          {preview.blockers.map((b) => <p key={b} className="flag bad" role="alert"><Alert /> {b}</p>)}
          {!blocked && preview.warnings.map((w) => <p key={w} className="flag"><Alert /> {w}</p>)}
          {!blocked && (
            <>
              <label htmlFor="import-replaces">Replaces (optional)</label>
              <input id="import-replaces" className="field" placeholder="For example Notion" value={replaces}
                     onChange={(e) => setReplaces(e.target.value)} />
            </>
          )}
        </div>
      )}
      <footer>
        <button className="ghost" onClick={() => dialog.current?.close()}>Cancel</button>
        {preview && !blocked && <button className="primary" disabled={busy} onClick={add}>Add and install</button>}
      </footer>
    </dialog>
  );
}
