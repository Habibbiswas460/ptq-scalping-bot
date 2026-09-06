"""Presentation shell: theme, page assembly, finding blocks, linked-selection behaviour.

Charts are inline SVG from research.svg. The only script on the page is a short vanilla
listener that keeps every view pointed at the same event when one is clicked — the linked
requirement — with no library and no network fetch.
"""
from __future__ import annotations

import datetime as _dt
import html
import os
from typing import Dict, List, Optional, Sequence

from research import provenance as prov

FONTS = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Zilla+Slab:wght@600;700&family=Source+Sans+3:wght@400;600&'
         'family=IBM+Plex+Mono:wght@400;500&display=swap">')

CSS = """
:root{--ground:#F6F8F7;--surface:#fff;--surface2:#EEF2F0;--ink:#141C1B;--ink2:#4E5C59;
--ink3:#7C8A87;--rule:#DBE3E0;--grid:#E7EDEB;--grid-strong:#C2CECA;--accent:#1D4E57;
--accent-soft:#E3EDEE;--up:#2C6E52;--dn:#8A3247;--warn:#99631C;--heat:#1D4E57;--nodata:#EEF2F0;
--sel:#F0D9A8;
--c-real-bg:#E2F0E9;--c-real:#2C6E52;--c-estimated-bg:#F7EBD8;--c-estimated:#99631C;
--c-reconstructed-bg:#E5E9F5;--c-reconstructed:#3F5591;--c-missing-bg:#F6E2E6;--c-missing:#8A3247;
--c-invalid-bg:#EDE3F3;--c-invalid:#6B3E8F;--c-live-only-bg:#E3EDEE;--c-live-only:#1D4E57}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--ground:#0E1413;
--surface:#151D1C;--surface2:#1D2726;--ink:#E4EBE8;--ink2:#A2B0AD;--ink3:#74827F;--rule:#26322F;
--grid:#1E2A28;--grid-strong:#35443F;--accent:#74B9C0;--accent-soft:#16302F;--up:#6BC49A;
--dn:#DE8095;--warn:#D9A65C;--heat:#74B9C0;--nodata:#1A2322;--sel:#4A3A1C;
--c-real-bg:#142A21;--c-real:#6BC49A;--c-estimated-bg:#2C2314;--c-estimated:#D9A65C;
--c-reconstructed-bg:#1A1F30;--c-reconstructed:#8FA3DC;--c-missing-bg:#2E161C;--c-missing:#DE8095;
--c-invalid-bg:#241A2E;--c-invalid:#B98FD6;--c-live-only-bg:#16302F;--c-live-only:#74B9C0}}
:root[data-theme="dark"]{--ground:#0E1413;--surface:#151D1C;--surface2:#1D2726;--ink:#E4EBE8;
--ink2:#A2B0AD;--ink3:#74827F;--rule:#26322F;--grid:#1E2A28;--grid-strong:#35443F;
--accent:#74B9C0;--accent-soft:#16302F;--up:#6BC49A;--dn:#DE8095;--warn:#D9A65C;--heat:#74B9C0;
--nodata:#1A2322;--sel:#4A3A1C;--c-real-bg:#142A21;--c-real:#6BC49A;--c-estimated-bg:#2C2314;
--c-estimated:#D9A65C;--c-reconstructed-bg:#1A1F30;--c-reconstructed:#8FA3DC;
--c-missing-bg:#2E161C;--c-missing:#DE8095;--c-invalid-bg:#241A2E;--c-invalid:#B98FD6;
--c-live-only-bg:#16302F;--c-live-only:#74B9C0}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:"Source Sans 3",
-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;line-height:1.6;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1140px;margin:0 auto;padding:0 28px 96px}
header.top{padding:48px 0 24px;border-bottom:2px solid var(--ink);margin-bottom:30px}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.14em;
text-transform:uppercase;color:var(--ink3);margin:0 0 12px}
h1{font-family:"Zilla Slab",Georgia,serif;font-weight:700;font-size:clamp(1.9rem,4.4vw,2.9rem);
line-height:1.07;margin:0 0 12px;letter-spacing:-.015em;text-wrap:balance}
.standfirst{font-size:1.06rem;color:var(--ink2);max-width:66ch;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:18px;
font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--ink3)}
.meta b{color:var(--ink2);font-weight:500}
.toc{display:flex;flex-wrap:wrap;gap:5px 8px;margin-top:16px}
.toc a{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;color:var(--ink2);
text-decoration:none;border:1px solid var(--rule);padding:2px 7px;border-radius:2px;
background:var(--surface)}
.toc a:hover{border-color:var(--accent);color:var(--accent)}
.toc a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h2.sec{font-family:"Zilla Slab",Georgia,serif;font-weight:600;font-size:1.46rem;
margin:48px 0 4px;letter-spacing:-.008em;text-wrap:balance;scroll-margin-top:14px}
h2.sec .num{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.7em;
color:var(--accent);margin-right:9px;font-weight:500}
h3.sub{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;letter-spacing:.1em;
text-transform:uppercase;color:var(--ink3);margin:24px 0 8px;font-weight:500;
border-top:1px solid var(--rule);padding-top:11px}
p{max-width:72ch;margin:0 0 12px}
p.cap{font-size:14px;color:var(--ink2);max-width:76ch}
p.none{font-size:14px;color:var(--ink3);font-style:italic}
.chart{display:block;width:100%;height:auto;margin:10px 0 14px;background:var(--surface);
border:1px solid var(--rule)}
text.ax{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:9.5px;fill:var(--ink3)}
text.ax-em{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;fill:var(--ink2)}
text.ct{font-size:12.5px;font-weight:600;fill:var(--ink)}
text.cs{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;fill:var(--ink3)}
text.hm{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;fill:var(--ink)}
text.hm-hi{fill:var(--surface)}
text.hm-none{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:9px;fill:var(--ink3)}
.scroller{overflow-x:auto;border:1px solid var(--rule);background:var(--surface);margin:0 0 16px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 11px;border-bottom:1px solid var(--rule);white-space:nowrap}
td.wrap-cell{white-space:normal;min-width:230px}
thead th{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;letter-spacing:.08em;
text-transform:uppercase;color:var(--ink3);font-weight:500;background:var(--surface2)}
tbody tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right;font-family:"IBM Plex Mono",ui-monospace,monospace;
font-variant-numeric:tabular-nums}
td.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px}
td.none-cell{color:var(--ink3)}
tr[data-event]{cursor:pointer}
tr[data-event]:hover td{background:var(--surface2)}
tr.is-sel td{background:var(--sel)}
[data-event].is-sel{outline:2px solid var(--accent)}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:0 24px;
border:1px solid var(--rule);background:var(--surface);padding:9px 15px;margin:0 0 16px}
.kv-row{display:flex;justify-content:space-between;gap:14px;padding:4px 0;
border-bottom:1px solid var(--rule);font-size:13.5px}
.kv-k{color:var(--ink2)}
.kv-v{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums;
text-align:right}
.chip{display:inline-block;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:9.5px;
letter-spacing:.08em;text-transform:uppercase;padding:2px 6px;border-radius:2px;font-weight:500}
.c-real{background:var(--c-real-bg);color:var(--c-real)}
.c-estimated{background:var(--c-estimated-bg);color:var(--c-estimated)}
.c-reconstructed{background:var(--c-reconstructed-bg);color:var(--c-reconstructed)}
.c-missing{background:var(--c-missing-bg);color:var(--c-missing)}
.c-invalid{background:var(--c-invalid-bg);color:var(--c-invalid)}
.c-live-only{background:var(--c-live-only-bg);color:var(--c-live-only)}
.flag{border:1px solid var(--rule);border-left:3px solid var(--dn);background:var(--surface);
padding:12px 15px;margin:0 0 16px}
.flag.good{border-left-color:var(--up)}
.flag.note{border-left-color:var(--accent)}
.flag h4{margin:0 0 4px;font-size:.94rem;font-weight:600}
.flag p{margin:0;font-size:14px;color:var(--ink2);max-width:68ch}
.find{border:1px solid var(--rule);border-left:3px solid var(--accent);background:var(--surface);
padding:13px 17px;margin:12px 0 24px}
.find dl{margin:0;display:grid;grid-template-columns:120px minmax(0,1fr);gap:5px 14px}
.find dt{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;letter-spacing:.08em;
text-transform:uppercase;color:var(--ink3);padding-top:3px}
.find dd{margin:0;font-size:14.5px;color:var(--ink)}
.find dd.soft{color:var(--ink2)}
@media(max-width:640px){.find dl{grid-template-columns:minmax(0,1fr);gap:1px 0}
.find dt{padding-top:8px}}
footer.end{border-top:2px solid var(--ink);padding-top:16px;margin-top:40px;font-size:14px;
color:var(--ink2);max-width:72ch}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.86em;background:var(--surface2);
padding:1px 5px;border-radius:3px}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

LINK_JS = """
(function(){
  // Linked selection: clicking any element carrying data-event highlights every view that
  // refers to the same event, so the market chart, the option chart and the tables all point
  // at one instant instead of having to be lined up by eye.
  function clear(){document.querySelectorAll('.is-sel').forEach(function(n){n.classList.remove('is-sel');});}
  function select(id){
    clear();
    document.querySelectorAll('[data-event="'+id+'"]').forEach(function(n){n.classList.add('is-sel');});
    var first=document.querySelector('svg [data-event="'+id+'"]');
    if(first&&first.scrollIntoView){first.scrollIntoView({block:'center',behavior:'auto'});}
  }
  document.addEventListener('click',function(e){
    var t=e.target.closest?e.target.closest('[data-event]'):null;
    if(!t){return;}
    var id=t.getAttribute('data-event');
    if(t.classList.contains('is-sel')){clear();}else{select(id);}
  });
  document.addEventListener('keydown',function(e){if(e.key==='Escape'){clear();}});
})();
"""


class Raw(str):
    """Markup that is already rendered and escaped. esc() passes it through, so a
    chip built here survives being handed to table() or kv() as a cell value -
    without this those helpers escape it again and the reader sees the tag text
    instead of the provenance chip."""


def esc(s) -> str:
    if isinstance(s, Raw):
        return str(s)
    return html.escape(str(s), quote=True)


def chip(field: str) -> Raw:
    label, state = prov.chip(field)
    return Raw(f'<span class="chip c-{state}">{esc(label)}</span>')


def finding(finding_: str, evidence: str, confidence: str, action: str, next_: str) -> Dict:
    """The mandatory shape. Action is what to DO, never an automatic threshold change."""
    return {"finding": finding_, "evidence": evidence, "confidence": confidence,
            "action": action, "next": next_}


def findings_html(items: Sequence[Dict]) -> str:
    out = []
    for f in items:
        out.append("<div class='find'><dl>"
                   f"<dt>Finding</dt><dd>{f['finding']}</dd>"
                   f"<dt>Evidence</dt><dd class='soft'>{f['evidence']}</dd>"
                   f"<dt>Confidence</dt><dd class='soft'>{f['confidence']}</dd>"
                   f"<dt>Action</dt><dd>{f['action']}</dd>"
                   f"<dt>Next test</dt><dd class='soft'>{f['next']}</dd></dl></div>")
    return "".join(out)


def kv(rows) -> str:
    out = ["<div class='kv'>"]
    for k, v in rows:
        out.append(f"<div class='kv-row'><span class='kv-k'>{esc(k)}</span>"
                   f"<span class='kv-v'>{esc(v)}</span></div>")
    out.append("</div>")
    return "".join(out)


def table(headers: Sequence, rows: Sequence[Sequence], num_cols=(), row_attrs=None) -> str:
    out = ["<div class='scroller'><table><thead><tr>"]
    for i, h in enumerate(headers):
        out.append(f"<th class='{'num' if i in num_cols else ''}'>{esc(h)}</th>")
    out.append("</tr></thead><tbody>")
    for j, r in enumerate(rows):
        attr = (row_attrs or {}).get(j, "")
        out.append(f"<tr {attr}>")
        for i, v in enumerate(r):
            cls = "num" if i in num_cols else ""
            if v is None or v == "":
                out.append(f"<td class='{cls} none-cell'>—</td>")
            else:
                out.append(f"<td class='{cls}'>{esc(v)}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


class Page:
    def __init__(self, title: str, h1: str, standfirst: str, meta: Sequence):
        self.title, self.h1, self.standfirst, self.meta = title, h1, standfirst, meta
        self.sections: List = []

    def add(self, name: str, body: str, finds: Sequence[Dict] = ()) -> None:
        self.sections.append((name, body, list(finds)))

    def html(self) -> str:
        toc = "".join(f"<a href='#s{i+1}'>{i+1:02d} {esc(n)}</a>"
                      for i, (n, _, _) in enumerate(self.sections))
        body = []
        for i, (name, content, finds) in enumerate(self.sections):
            body.append(f"<h2 class='sec' id='s{i+1}'><span class='num'>{i+1:02d}</span>"
                        f"{esc(name)}</h2>{content}{findings_html(finds)}")
        meta = "".join(f"<span><b>{esc(k)}</b> {esc(v)}</span>" for k, v in self.meta)
        return (f"<title>{esc(self.title)}</title>{FONTS}<style>{CSS}</style>"
                f"<div class='wrap'><header class='top'>"
                f"<p class='eyebrow'>PTQ research instrument · generated "
                f"{_dt.datetime.now():%Y-%m-%d %H:%M}</p>"
                f"<h1>{esc(self.h1)}</h1><p class='standfirst'>{self.standfirst}</p>"
                f"<div class='meta'>{meta}</div><div class='toc'>{toc}</div></header>"
                f"{''.join(body)}"
                f"<footer class='end'><p>Generated by the research package in this repository. "
                f"Inline SVG, no plotting dependency, no network fetch beyond the webfonts. "
                f"Click any trade row to highlight the same event everywhere; Esc clears.</p>"
                f"</footer></div><script>{LINK_JS}</script>")

    def write(self, path: str) -> str:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(self.html())
        return path
