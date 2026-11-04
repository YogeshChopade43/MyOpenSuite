import { useCallback, useEffect, useState } from "react";
import { AppInfo, listApps } from "./api";
import { Apps, Store } from "./Icons";
import { JobLog } from "./JobLog";
import { Tile } from "./Tile";

type Tab = "mine" | "marketplace";

export function App() {
  const [apps, setApps] = useState<AppInfo[] | null>(null);
  const [banner, setBanner] = useState("");
  const [tab, setTab] = useState<Tab>("mine");
  const [category, setCategory] = useState("");
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

  const all = apps ?? [];
  const names = Object.fromEntries(all.map((a) => [a.id, a.name]));
  const installed = all.filter((a) => a.status !== "not_installed" || a.job?.state === "running");
  const running = installed.filter((a) => a.status === "running").length;
  const categories = [...new Set(all.map((a) => a.category).filter(Boolean))].sort();
  // Featured: the biggest app you don't have yet, else the biggest of all
  const bySize = all.filter((a) => a.size_gb > 0).sort((a, b) => b.size_gb - a.size_gb);
  const featured = bySize.find((a) => a.status === "not_installed") ?? bySize[0];
  const market = tab === "marketplace";
  const hero = market && !category ? featured : undefined;
  const shown = market ? all.filter((a) => a !== hero && (!category || a.category === category)) : installed;

  const tile = (a: AppInfo, i: number, variant: "card" | "hero") => (
    <Tile key={a.id} app={a} index={i} variant={variant} manage={!market} names={names} onChanged={refresh}
          onShowLog={(mode) => setLog({ id: a.id, mode })} />
  );

  return (
    <>
      {banner && <div className="banner" role="alert">{banner}</div>}
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden />
          <h1>MyOpenSuite</h1>
        </div>
        <nav className="tabs" data-active={tab}>
          <button aria-current={!market ? "page" : undefined} onClick={() => setTab("mine")}><Apps /> My apps</button>
          <button aria-current={market ? "page" : undefined} onClick={() => setTab("marketplace")}><Store /> Marketplace</button>
        </nav>
      </header>
      <main>
        {!market && (
          <div className="heading">
            <h2>My apps</h2>
            <p>{apps ? `${running} of ${installed.length} running` : " "}</p>
          </div>
        )}
        {hero && <div className="feature-slot" key={`hero-${hero.id}`}>{tile(hero, 0, "hero")}</div>}
        {market && categories.length > 0 && (
          <div className="chips" role="group" aria-label="Filter by category">
            {["", ...categories].map((c) => (
              <button key={c || "all"} className="chip" aria-pressed={category === c} onClick={() => setCategory(c)}>
                {c || "All"}
              </button>
            ))}
          </div>
        )}
        {apps && !market && shown.length === 0 && (
          <div className="empty">
            <p>Nothing installed yet.</p>
            <button className="primary" onClick={() => setTab("marketplace")}><Store /> Browse the Marketplace</button>
          </div>
        )}
        <section className="grid" key={`grid-${tab}-${category}`} aria-busy={!apps}>
          {!apps && !banner && [0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="tile skeleton" aria-hidden />)}
          {shown.map((a, i) => tile(a, i, "card"))}
        </section>
      </main>
      {log && (
        <JobLog id={log.id} name={names[log.id] ?? log.id} mode={log.mode}
                onClose={() => { setLog(null); refresh(); }} />
      )}
    </>
  );
}
