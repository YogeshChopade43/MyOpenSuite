import { useEffect, useRef, useState } from "react";
import { getSecrets, Secret } from "./api";

function SecretRow({ s }: { s: Secret }) {
  const [shown, setShown] = useState(false);
  const [copied, setCopied] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(s.value);
      setCopied("Copied");
    } catch {
      setShown(true);
      input.current?.select();
      setCopied("Press Ctrl+C");
    }
    window.setTimeout(() => setCopied(""), 2000);
  };
  return (
    <div className="secret">
      <label htmlFor={`secret-${s.name}`}>{s.description}</label>
      <div className="secret-row">
        <input ref={input} id={`secret-${s.name}`} readOnly type={shown ? "text" : "password"} value={s.value}
               onFocus={(e) => e.target.select()} />
        <button className="ghost" onClick={() => setShown((v) => !v)}>{shown ? "Hide" : "Show"}</button>
        <button onClick={copy}>{copied || "Copy"}</button>
      </div>
    </div>
  );
}

/** Modal listing an app's generated secrets with show/copy controls. */
export function Credentials({ id, name, onClose }: { id: string; name: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [secrets, setSecrets] = useState<Secret[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    dialog.current?.showModal();
    getSecrets(id).then(setSecrets, (e) => setError((e as Error).message));
  }, [id]);

  return (
    <dialog ref={dialog} className="modal" onClose={onClose}>
      <header><h2>{name} — credentials</h2></header>
      <div className="secrets">
        {error && <p className="error" role="alert">{error}</p>}
        {!secrets && !error && <p className="note">Loading…</p>}
        {secrets?.map((s) => <SecretRow key={s.name} s={s} />)}
      </div>
      <footer><button className="ghost" onClick={() => dialog.current?.close()}>Close</button></footer>
    </dialog>
  );
}
