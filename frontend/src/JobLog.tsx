import { useEffect, useRef, useState } from "react";
import { getJob, getLogs, install, JobInfo } from "./api";

/** Modal showing an install/update job log (mode "job") or the app's container logs (mode "logs"). */
export function JobLog({ id, name, mode, onClose }: {
  id: string; name: string; mode: "job" | "logs"; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const pre = useRef<HTMLPreElement>(null);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [text, setText] = useState("Loading…");

  useEffect(() => { dialog.current?.showModal(); }, []);

  const [run, setRun] = useState(0); // bumped by Retry to restart polling

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = async () => {
      try {
        if (mode === "logs") {
          setText((await getLogs(id)).logs || "(no output)");
          return;
        }
        const j = await getJob(id);
        if (cancelled) return;
        setJob(j);
        setText(j.log.join("\n") || "Waiting for output…");
        if (j.state === "running") timer = window.setTimeout(load, 1000);
      } catch (e) {
        if (!cancelled) setText((e as Error).message);
      }
    };
    load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [id, mode, run]);

  useEffect(() => { pre.current?.scrollTo(0, pre.current.scrollHeight); }, [text]);

  const retry = async () => {
    try { await install(id); } catch (e) { setText((e as Error).message); }
    setRun((n) => n + 1);
  };

  const title = mode === "logs" ? `${name} — logs` : `${name} — ${job?.kind ?? "job"} (${job?.state ?? "…"})`;
  return (
    <dialog ref={dialog} className="modal" onClose={onClose}>
      <header><h2>{title}</h2></header>
      <pre ref={pre} className="log">{text}</pre>
      <footer>
        {job?.state === "error" && <button onClick={retry}>Retry</button>}
        <button className="ghost" onClick={() => dialog.current?.close()}>Close</button>
      </footer>
    </dialog>
  );
}
