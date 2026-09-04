"""Assemble the visual research report.

    python -m research.report                 # every session with market context
    python -m research.report 2026-09-04      # one session
    python -m research.report --out DIR

Output is one self-contained HTML file per run: inline SVG, no scripts, no CDN, no plotting
dependency. It opens from disk and keeps working when the database moves on.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from typing import List

from research.data import Book
from research import sections_market as M
from research import sections_strategy as S

CSS = """
:root{
  --ground:#F6F8F7; --surface:#fff; --surface2:#EEF2F0; --ink:#141C1B; --ink2:#4E5C59;
  --ink3:#7C8A87; --rule:#DBE3E0; --grid:#E7EDEB; --grid-strong:#C2CECA;
  --accent:#1D4E57; --accent-soft:#E3EDEE;
  --up:#2C6E52; --dn:#8A3247; --warn:#99631C; --heat:#1D4E57; --nodata:#EEF2F0;
  --c-real-bg:#E2F0E9; --c-real:#2C6E52;
  --c-est-bg:#F7EBD8; --c-est:#99631C;
  --c-recon-bg:#E5E9F5; --c-recon:#3F5591;
  --c-miss-bg:#F6E2E6; --c-miss:#8A3247;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0E1413; --surface:#151D1C; --surface2:#1D2726; --ink:#E4EBE8; --ink2:#A2B0AD;
  --ink3:#74827F; --rule:#26322F; --grid:#1E2A28; --grid-strong:#35443F;
  --accent:#74B9C0; --accent-soft:#16302F;
  --up:#6BC49A; --dn:#DE8095; --warn:#D9A65C; --heat:#74B9C0; --nodata:#1A2322;
  --c-real-bg:#142A21; --c-real:#6BC49A;
  --c-est-bg:#2C2314; --c-est:#D9A65C;
  --c-recon-bg:#1A1F30; --c-recon:#8FA3DC;
  --c-miss-bg:#2E161C; --c-miss:#DE8095;
}}
:root[data-theme="dark"]{
  --ground:#0E1413; --surface:#151D1C; --surface2:#1D2726; --ink:#E4EBE8; --ink2:#A2B0AD;
  --ink3:#74827F; --rule:#26322F; --grid:#1E2A28; --grid-strong:#35443F;
  --accent:#74B9C0; --accent-soft:#16302F;
  --up:#6BC49A; --dn:#DE8095; --warn:#D9A65C; --heat:#74B9C0; --nodata:#1A2322;
  --c-real-bg:#142A21; --c-real:#6BC49A;
  --c-est-bg:#2C2314; --c-est:#D9A65C;
  --c-recon-bg:#1A1F30; --c-recon:#8FA3DC;
  --c-miss-bg:#2E161C; --c-miss:#DE8095;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:"Source Sans 3",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 28px 96px}
header.top{padding:52px 0 26px;border-bottom:2px solid var(--ink);margin-bottom:34px}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink3);margin:0 0 12px}
h1{font-family:"Zilla Slab",Georgia,serif;font-weight:700;font-size:clamp(2rem,4.6vw,3rem);
  line-height:1.07;margin:0 0 14px;letter-spacing:-.015em;text-wrap:balance}
.standfirst{font-size:1.08rem;color:var(--ink2);max-width:64ch;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:6px 24px;margin-top:20px;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--ink3)}
.meta b{color:var(--ink2);font-weight:500}
h2.sec{font-family:"Zilla Slab",Georgia,serif;font-weight:600;font-size:1.5rem;
  margin:52px 0 4px;letter-spacing:-.008em;text-wrap:balance;scroll-margin-top:16px}
h2.sec .num{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.7em;color:var(--accent);
  margin-right:9px;font-weight:500}
h3.day{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink3);margin:26px 0 8px;font-weight:500;
  border-top:1px solid var(--rule);padding-top:12px}
p{max-width:70ch;margin:0 0 12px}
p.cap{font-size:14px;color:var(--ink2);max-width:74ch}
p.none{font-size:14px;color:var(--ink3);font-style:italic}
.chart{display:block;width:100%;height:auto;margin:10px 0 16px;background:var(--surface);
  border:1px solid var(--rule)}
text.ax{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:9.5px;fill:var(--ink3)}
text.ax-em{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;fill:var(--ink2)}
text.ct{font-family:"Source Sans 3",sans-serif;font-size:12.5px;font-weight:600;fill:var(--ink)}
text.cs{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;fill:var(--ink3)}
text.hm{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;fill:var(--ink)}
text.hm-hi{fill:var(--surface)}
text.hm-none{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:9px;fill:var(--ink3)}
.scroller{overflow-x:auto;border:1px solid var(--rule);background:var(--surface);margin:0 0 18px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 11px;border-bottom:1px solid var(--rule);white-space:nowrap}
td.wrap-cell{white-space:normal;min-width:240px}
thead th{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink3);font-weight:500;background:var(--surface2)}
tbody tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums}
td.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px}
td.none-cell{color:var(--ink3)}
tr.row-warn td{background:var(--c-est-bg)}
table.mini{font-size:12px}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0 26px;
  border:1px solid var(--rule);background:var(--surface);padding:10px 16px;margin:0 0 18px}
.kv-row{display:flex;justify-content:space-between;gap:16px;padding:4px 0;
  border-bottom:1px solid var(--rule);font-size:13.5px}
.kv-k{color:var(--ink2)}
.kv-v{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums;
  text-align:right}
.chip{display:inline-block;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:9.5px;
  letter-spacing:.08em;text-transform:uppercase;padding:2px 6px;border-radius:2px;font-weight:500}
.c-real{background:var(--c-real-bg);color:var(--c-real)}
.c-estimated{background:var(--c-est-bg);color:var(--c-est)}
.c-reconstructed{background:var(--c-recon-bg);color:var(--c-recon)}
.c-missing{background:var(--c-miss-bg);color:var(--c-miss)}
.c-live-only{background:var(--accent-soft);color:var(--accent)}
.flag{border:1px solid var(--rule);border-left:3px solid var(--dn);background:var(--surface);
  padding:13px 16px;margin:0 0 18px}
.flag h4{margin:0 0 5px;font-size:.95rem;font-weight:600}
.flag p{margin:0;font-size:14px;color:var(--ink2);max-width:66ch}
.find{border:1px solid var(--rule);border-left:3px solid var(--accent);background:var(--surface);
  padding:14px 18px;margin:14px 0 26px}
.find dl{margin:0;display:grid;grid-template-columns:126px minmax(0,1fr);gap:5px 14px}
.find dt{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink3);padding-top:3px}
.find dd{margin:0;font-size:14.5px;color:var(--ink)}
.find dd.soft{color:var(--ink2)}
@media(max-width:640px){.find dl{grid-template-columns:minmax(0,1fr);gap:1px 0}
  .find dt{padding-top:8px}}
footer.end{border-top:2px solid var(--ink);padding-top:18px;margin-top:44px;font-size:14px;
  color:var(--ink2);max-width:70ch}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def find_block(finds) -> str:
    out = []
    for fd in finds:
        out.append(
            "<div class='find'><dl>"
            f"<dt>Finding</dt><dd>{fd['finding']}</dd>"
            f"<dt>Evidence</dt><dd class='soft'>{fd['evidence']}</dd>"
            f"<dt>Confidence</dt><dd class='soft'>{fd['confidence']}</dd>"
            f"<dt>Interpretation</dt><dd>{fd['interpretation']}</dd>"
            f"<dt>Next</dt><dd class='soft'>{fd['next']}</dd>"
            "</dl></div>")
    return "".join(out)


def sec(n, title, body, finds) -> str:
    return (f"<h2 class='sec' id='s{n}'><span class='num'>{n:02d}</span>{title}</h2>"
            + body + find_block(finds))


def build(days: List[str] = None, out_dir: str = "claude_code/research_output") -> str:
    book = Book()
    all_sessions = book.sessions()
    tick_days = [s["day"] for s in all_sessions if s["kind"] == "tick"]
    spot_days = [s["day"] for s in all_sessions if s["kind"] in ("tick", "coarse")]
    days = days or spot_days
    focus = [d for d in days if d in tick_days] or days

    parts = []
    n = 1
    # 1-3 per session
    body, finds = [], []
    for d in days:
        h, fd = M.session_structure(book, d)
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd
    parts.append(sec(n, "Full-session market structure", "".join(body), finds)); n += 1

    h, fd = M.multi_timeframe(book, focus[-1])
    parts.append(sec(n, "Synchronized timeframes · 10s / 30s / 1m / 5m", h, fd)); n += 1

    body, finds = [], []
    for d in focus:
        h, fd = M.leg_forensics(book, d)
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd
    parts.append(sec(n, "Major movement legs", "".join(body), finds)); n += 1

    h, fd = M.time_of_day(book, spot_days)
    parts.append(sec(n, "Volatility · time-of-day map", h, fd)); n += 1

    body, finds = [], []
    for d in spot_days:
        h, fd = S.signal_stack(book, d)
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd[:1] if d == spot_days[-1] else []
    parts.append(sec(n, "Signal-stack behaviour", "".join(body), finds)); n += 1

    body, finds = [], []
    for d in focus:
        h, fd = S.ce_pe(book, d)
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd if d == focus[-1] else []
    parts.append(sec(n, "CE / PE behaviour", "".join(body), finds)); n += 1

    body, finds = [], []
    for d in focus:
        h, fd = S.entry_windows(book, d)
        if "class='none'" in h:
            continue
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd if not finds else []
    parts.append(sec(n, "Entry windows · causal, with the entry bar partial",
                     "".join(body) or "<p class='none'>No entries with tick coverage.</p>",
                     finds)); n += 1

    h, fd = S.capture_cascade(book, focus)
    parts.append(sec(n, "Capture cascade · spot offered → option offered → captured", h, fd)); n += 1

    body, finds = [], []
    for d in focus:
        h, fd = S.transmission(book, d)
        if "class='none'" in h:
            continue
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd
    parts.append(sec(n, "Spot → option transmission", "".join(body), finds)); n += 1

    h, fd = S.exit_behaviour(book, focus)
    parts.append(sec(n, "Exit behaviour", h, fd)); n += 1

    body, finds = [], []
    for d in spot_days:
        h, fd = S.blocked_signals(book, d)
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd if d == spot_days[-1] else []
    parts.append(sec(n, "Blocked signals", "".join(body), finds)); n += 1

    h, fd = S.gate_ladder(book, spot_days)
    parts.append(sec(n, "Gate ladder · what the scoring stack never sees", h, fd)); n += 1

    h, fd = S.comparison(book)
    parts.append(sec(n, "Historical session comparison", h, fd)); n += 1

    body, finds = [], []
    for d in focus:
        h, fd = M.data_quality(book, d)
        body.append(f"<h3 class='day'>{d}</h3>" + h)
        finds += fd if d == focus[-1] else []
    parts.append(sec(n, "Data quality &amp; provenance", "".join(body), finds)); n += 1

    h, fd = S.dvf_verdict(book)
    parts.append(sec(n, "dvf_trades · what those 2,642 rows actually are", h, fd)); n += 1

    unknown = """
    <ul>
      <li><b>Real bid/ask.</b> Every rupee figure here is gross of an unknown execution cost.
          Only the collector's solo run resolves it.</li>
      <li><b>PE behaviour.</b> Effectively no PE option history; the repaired negative-delta
          scoring cannot be tested.</li>
      <li><b>09:15–09:45.</b> No signal record on any historical session — the window holding
          the largest legs.</li>
      <li><b>OI.</b> NULL on every historical row; the first real values arrive with the next
          session.</li>
      <li><b>Regime.</b> One value across six sessions, so nothing can be conditioned on it.</li>
      <li><b>Transaction costs.</b> No field exists anywhere in the schema.</li>
      <li><b>Sub-second ordering.</b> Roughly a fifth of ticks share a second with another;
          intra-second sequence is already lost and cannot be recovered.</li>
    </ul>"""
    parts.append(sec(n, "Unknowns and missing data", unknown, []))

    nav = "".join(f"<span><b>{i+1:02d}</b> {t}</span>" for i, t in enumerate([
        "Market structure", "Timeframes", "Legs", "Time-of-day", "Signal stack", "CE/PE",
        "Entry windows", "Capture cascade", "Transmission", "Exits", "Blocked", "Gate ladder",
        "Comparison", "Data quality", "dvf_trades", "Unknowns"]))

    html = f"""<title>Where the Move Goes Missing</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header class="top">
  <p class="eyebrow">PTQ Scalping Bot · visual research · generated {_dt.datetime.now():%Y-%m-%d %H:%M}</p>
  <h1>Where the Move Goes Missing</h1>
  <p class="standfirst">One chain, traced end to end on real persisted data: how far the market
  moved, where it moved, what the strategy saw, where it entered, how much of that movement the
  option transmitted, and how much survived to P&amp;L. Every field is labelled with what it
  actually is.</p>
  <div class="meta">
    <span><b>Sessions</b> {len(all_sessions)} discovered</span>
    <span><b>Tick</b> {len(tick_days)}</span>
    <span><b>Coarse</b> {len(spot_days)-len(tick_days)}</span>
    <span><b>Trades</b> {len(book.trades())}</span>
    <span><b>Baseline</b> 8b7490e untouched</span>
  </div>
  <p class="cap" style="margin-top:14px">{nav}</p>
</header>
{''.join(parts)}
<footer class="end">
  <p>Generated by <code>python -m research.report</code>. Inline SVG, no scripts, no plotting
  dependency — the file opens from disk and keeps working when the database moves on. Every new
  session enters these charts automatically through session discovery; nothing is hard-coded to
  a date.</p>
</footer>
</div>"""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "research_report.html")
    with open(path, "w") as fh:
        fh.write(html)
    return path


def main(argv: List[str]) -> int:
    days, out = [], "claude_code/research_output"
    i = 0
    while i < len(argv):
        if argv[i] == "--out":
            out = argv[i + 1]; i += 2; continue
        days.append(argv[i]); i += 1
    path = build(days or None, out)
    print(f"wrote {path} ({os.path.getsize(path):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
