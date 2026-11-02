import { useCallback, useEffect, useState } from "react";
import { AppInfo, listApps } from "./api";
import { JobLog } from "./JobLog";
import { Tile } from "./Tile";

type Tab = "dashboard" | "marketplace";

export function App() {
  const [apps, setApps] = useState<AppInfo[] | null>(null);
  const [banner, setBanner] = useState("");
  const [tab, setTab] = useState<Tab>("dashboard");
  const [log, setLog] = useState<{ id: string; mode: "job" | "logs" } | null>(null);

  const refresh = useCallback(async () => {
    try {
      setApps(await listApps());
      setBanner("");
    } catch (e) {
      setBanner((e as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  const names = Object.fromEntries((apps ?? []).map((a) => [a.id, a.name]));
  const installed = (apps ?? []).filter((a) => a.status !== "not_installed" || a.job?.state === "running");
  const shown = tab === "dashboard" ? installed : apps ?? [];

  return (
    <>
      {banner && <div className="banner" role="alert">{banner}</div>}
      <header className="top">
        <h1>MyOpenSuite</h1>
        <nav>
          {(["dashboard", "marketplace"] as Tab[]).map((t) => (
            <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
              {t === "dashboard" ? "Dashboard" : "Marketplace"}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {apps && shown.length === 0 && (
          <p className="empty">
            {tab === "dashboard"
              ? <>Nothing installed yet. <button className="link" onClick={() => setTab("marketplace")}>Browse the Marketplace</button></>
              : "The catalog is empty."}
          </p>
        )}
        <section className="grid">
          {shown.map((a) => (
            <Tile key={a.id} app={a} names={names} onChanged={refresh}
                  onShowLog={(mode) => setLog({ id: a.id, mode })} />
          ))}
        </section>
      </main>
      {log && (
        <JobLog id={log.id} name={names[log.id] ?? log.id} mode={log.mode}
                onClose={() => { setLog(null); refresh(); }} />
      )}
    </>
  );
}
