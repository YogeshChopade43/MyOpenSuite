import { useCallback, useEffect, useState } from "react";
import { AppInfo, listApps } from "./api";
import { Apps, Store } from "./Icons";
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
  const running = installed.filter((a) => a.status === "running").length;
  const shown = tab === "dashboard" ? installed : apps ?? [];

  return (
    <>
      <div className="aurora" aria-hidden><i /><i /><i /></div>
      {banner && <div className="banner" role="alert">{banner}</div>}
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden />
          <h1>MyOpenSuite</h1>
        </div>
        <nav className="tabs" data-active={tab}>
          <button aria-current={tab === "dashboard" ? "page" : undefined} onClick={() => setTab("dashboard")}>
            <Apps /> Dashboard
          </button>
          <button aria-current={tab === "marketplace" ? "page" : undefined} onClick={() => setTab("marketplace")}>
            <Store /> Marketplace
          </button>
        </nav>
      </header>
      <main>
        <div className="hero" key={`hero-${tab}`}>
          <h2>{tab === "dashboard" ? "Your apps" : "Marketplace"}</h2>
          <p>
            {tab === "marketplace"
              ? "Open-source, self-hosted replacements for paid AI tools."
              : apps ? `${running} of ${installed.length} running` : " "}
          </p>
        </div>
        {apps && shown.length === 0 && (
          <div className="empty">
            <p>{tab === "dashboard" ? "Nothing installed yet." : "The catalog is empty."}</p>
            {tab === "dashboard" && <button onClick={() => setTab("marketplace")}><Store /> Browse the Marketplace</button>}
          </div>
        )}
        <section className="grid" key={`grid-${tab}`} aria-busy={!apps}>
          {!apps && !banner && [0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="tile skeleton" aria-hidden />)}
          {shown.map((a, i) => (
            <Tile key={a.id} app={a} index={i} names={names} onChanged={refresh}
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
