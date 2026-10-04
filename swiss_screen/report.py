"""Static HTML report: a tabbed page (Map, Listings, Rental) with a Leaflet /
OpenStreetMap map, status-colored cards, and a CSV export. All badge logic lives
here so the template stays presentational. Cards and markers share one color
system so the map and the list read as one view.
"""

from __future__ import annotations

import html
import json
from datetime import datetime

from .config import commune_status, is_tourist, resale_hold_years, FILTERS
from .geocode import coords_for
from .detector import (BUILD_EXISTING, BUILD_NEW_PRIMARY, BUILD_NEW_MANAGED,
                       BUILD_NEW_OTHER, BUILD_UNKNOWN)

BUILD_META = {
    BUILD_EXISTING: ("b-existing", "existing / resale"),
    BUILD_NEW_MANAGED: ("b-amber", "new build, managed rental"),
    BUILD_NEW_OTHER: ("b-amber", "new build, type unstated"),
    BUILD_NEW_PRIMARY: ("b-rust", "new build, primary residence"),
    BUILD_UNKNOWN: ("b-info", "build type not stated"),
}

# marker fill by build status, matching the card spine colors
SPINE_COLOR = {
    "existing": "#1F7A5A", "new_managed": "#B0791C", "new_unspecified": "#B0791C",
    "new_primary": "#B4462F", "unknown": "#5E6E6B",
}


def esc(x):
    if x is None:
        return ""
    return html.escape(str(x))


def price_fmt(v):
    if v is None:
        return "n/a"
    try:
        return f"{int(v):,}".replace(",", "'")
    except (ValueError, TypeError):
        return "n/a"


def num_fmt(v, suffix=""):
    if v is None:
        return "n/a"
    try:
        f = float(v)
        s = str(int(f)) if f == int(f) else str(f)
        return f"{s}{suffix}"
    except (ValueError, TypeError):
        return "n/a"


def extra_badges(row):
    b = []
    muni = row.get("municipality", "")
    cs = commune_status(muni)
    pct = cs["pct"]
    pctlbl = f" ({pct:.0f}%)" if pct is not None else ""
    build = row.get("build_type", BUILD_UNKNOWN)
    build_is_new = build in (BUILD_NEW_PRIMARY, BUILD_NEW_MANAGED, BUILD_NEW_OTHER)

    if cs["status"] == "frozen":
        if build == BUILD_NEW_PRIMARY:
            b.append(('b-rust', "frozen commune + new primary: not buyable"))
        elif build == BUILD_EXISTING:
            b.append(('b-info', f"frozen commune{pctlbl}, resale is fine"))
        else:
            b.append(('b-amber', "frozen commune, verify build type"))
    elif cs["status"] == "open":
        if build_is_new:
            b.append(('b-open', f"new build allowed here, commune under 20%{pctlbl}"))
        else:
            b.append(('b-info', f"commune under 20%{pctlbl}, new build also allowed"))
    elif cs["status"] == "near":
        b.append(('b-amber', f"approaching 20%{pctlbl}, ARE status may flip"))
    elif build_is_new:
        b.append(('b-amber', "commune second-home status unknown, verify ARE"))

    tz = is_tourist(muni)
    if tz is False:
        b.append(('b-rust', "not open to non-resident foreign buyers (not a Lex Koller tourist location)"))
    elif tz is True:
        if cs["status"] == "open" and build_is_new:
            b.append(('b-open', "buyable new build: tourist zone + under 20%"))
        else:
            b.append(('b-agree', "designated tourist zone"))

    la = row.get("living_area_m2")
    if la is not None and la > FILTERS["living_max"]:
        b.append(('b-rust', f"over {FILTERS['living_max']} m2 Lex Koller limit"))
    hold = resale_hold_years(row.get("canton", ""))
    if hold:
        b.append(('b-info', f"{row.get('canton')}: no foreign resale within {hold}y"))
    if row.get("method") == "llm" and (row.get("confidence") or 0) < 0.6:
        b.append(('b-amber', "low confidence, verify"))
    return b


def snippet_html(description, snippet):
    if not snippet:
        return ""
    desc = description or ""
    pos = desc.lower().find(snippet.lower())
    if pos == -1:
        return f'<div class="snip">&hellip; <b>{esc(snippet)}</b> &hellip;</div>'
    s, e = max(0, pos - 70), min(len(desc), pos + len(snippet) + 70)
    pre, hit, post = esc(desc[s:pos]), esc(desc[pos:pos + len(snippet)]), esc(desc[pos + len(snippet):e])
    lead = "&hellip; " if s > 0 else ""
    trail = " &hellip;" if e < len(desc) else ""
    return f'<div class="snip">{lead}{pre}<b>{hit}</b>{post}{trail}</div>'


def align_badge(row):
    a = row.get("align")
    if a is None:
        return ('b-llm', "single source")
    if a is True:
        return ('b-agree', "rule + LLM agree")
    return ('b-rust', "rule vs LLM conflict")


def warnings(row):
    """Only the problems that would stop a purchase, in plain words."""
    muni = row.get("municipality", "")
    out = []
    if is_tourist(muni) is False:
        out.append("This commune is closed to non-resident foreign buyers.")
    if commune_status(muni)["status"] == "frozen" and row.get("build_type") == BUILD_NEW_PRIMARY:
        out.append("New build in a commune over 20% second homes: not buyable as a holiday home.")
    if row.get("method") == "llm" and (row.get("confidence") or 0) < 0.6:
        out.append("Low confidence: check the listing wording.")
    return out


def card_html(row, is_new):
    lid = row.get("listing_id", "")
    facts = []
    if row.get("rooms"):
        facts.append(f"{num_fmt(row.get('rooms'))} rooms")
    if row.get("living_area_m2"):
        facts.append(f"{num_fmt(row.get('living_area_m2'))} m&sup2;")
    if row.get("year_built"):
        facts.append(f"built {row.get('year_built')}")
    price = row.get("price_chf")
    price_html = f"CHF {price_fmt(price)}" if price else "Price on request"
    quote = (f'<blockquote class="quote">&ldquo;{esc(row.get("snippet"))}&rdquo;</blockquote>'
             if row.get("snippet") else "")
    warn = "".join(f'<p class="warn">{esc(w)}</p>' for w in warnings(row))
    return f"""<article class="card{' is-new' if is_new else ''}" data-canton="{esc(row.get('canton'))}" id="card-{esc(lid)}">
  <div class="top">
    <div>
      <p class="ptitle">{esc(row.get('title') or 'Untitled listing')}</p>
      <div class="loc">{esc(row.get('municipality'))}, {esc(row.get('canton'))}{' &middot; ' + ' &middot; '.join(facts) if facts else ''}</div>
    </div>
    <div class="price">{price_html}</div>
  </div>
  {quote}{warn}
  <a class="open" href="{esc(row.get('url') or '#')}" target="_blank" rel="noopener">Open listing &rarr;</a>
</article>"""


def _map_points(rows, coords):
    """Build the JSON array of markers for Leaflet, jittering co-located pins."""
    seen = {}
    points = []
    for row in rows:
        latlon = coords_for(row.get("municipality", ""), coords)
        if latlon is None:
            continue
        lat, lon = latlon
        # several listings in one commune share a centroid; nudge them apart
        n = seen.get((round(lat, 4), round(lon, 4)), 0)
        seen[(round(lat, 4), round(lon, 4))] = n + 1
        if n:
            lat += 0.0045 * ((n % 6) - 2.5) * 0.4
            lon += 0.0065 * ((n // 6) - 1) * 0.4
        cs = commune_status(row.get("municipality", ""))
        tz = is_tourist(row.get("municipality", ""))
        blocked = tz is False
        points.append({
            "id": row.get("listing_id", ""),
            "lat": round(lat, 5), "lon": round(lon, 5),
            "title": row.get("title", ""),
            "muni": f"{row.get('municipality','')}, {row.get('canton','')}",
            "price": price_fmt(row.get("price_chf")),
            "rooms": num_fmt(row.get("rooms")),
            "color": "#8a94a6" if blocked else SPINE_COLOR.get(row.get("build_type"), "#5E6E6B"),
            "blocked": blocked,
            "pct": (f"{cs['pct']:.0f}%" if cs["pct"] is not None else ""),
            "url": row.get("url", ""),
        })
    return points


def _csv_text(rows):
    import csv as _csv
    import io
    cols = ["listing_id", "canton", "municipality", "postal_code", "price_chf",
            "rooms", "living_area_m2", "year_built", "build_type", "method",
            "align", "confidence", "url", "title"]
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------

REPORT_CSS = """
<style>
:root{--paper:#F4F6F5;--surface:#fff;--ink:#16211F;--muted:#5E6E6B;--line:#DCE3E1;
--teal:#17706E;--teal-deep:#0E4C4B;--pine:#1F7A5A;--amber:#B0791C;--rust:#B4462F;--flag:#C0392B;
--mono:"IBM Plex Mono",ui-monospace,monospace;--disp:"Space Grotesk",system-ui,sans-serif;--body:"Inter",system-ui,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:var(--teal-deep)}
.wrap{max-width:1080px;margin:0 auto;padding:30px 24px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:18px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--teal-deep);margin:0 0 10px}
h1{font-family:var(--disp);font-weight:600;font-size:32px;letter-spacing:-.01em;margin:0}
.updated{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--pine);background:#E6F2EC;border:1px solid #BFDCCD;border-radius:999px;padding:4px 11px;margin-bottom:12px}
.updated::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--pine)}
.runmeta{font-family:var(--mono);font-size:12px;color:var(--muted);margin-top:8px}
.metrics{display:flex;gap:26px;margin:20px 0 4px;flex-wrap:wrap}
.metric{padding-right:26px;border-right:1px solid var(--line)}
.metric:last-child{border-right:none}
.metric .n{font-family:var(--mono);font-size:28px;font-weight:600}
.metric .l{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-top:6px}
.metric.hot .n{color:var(--teal)}
/* tab bar */
.tabs{display:flex;gap:4px;margin:26px 0 20px;border-bottom:1px solid var(--line)}
.tab{font-family:var(--disp);font-weight:500;font-size:15px;color:var(--muted);background:none;border:none;
border-bottom:2px solid transparent;padding:10px 16px;margin-bottom:-1px;cursor:pointer}
.tab[aria-selected=true]{color:var(--ink);border-bottom-color:var(--teal)}
.tab:focus-visible{outline:2px solid var(--teal);outline-offset:2px}
.tab .soon{font-family:var(--mono);font-size:10px;color:var(--muted);margin-left:6px}
.panel{display:none}
.panel.active{display:block}
/* map */
#map{height:520px;border:1px solid var(--line);border-radius:12px;overflow:hidden;z-index:0}
.maphint{font-family:var(--mono);font-size:12px;color:var(--muted);margin:10px 2px 0}
.leaflet-popup-content{font-family:var(--body);margin:12px 14px}
.popt{font-family:var(--disp);font-weight:600;font-size:14px;margin:0 0 2px}
.popm{font-family:var(--mono);font-size:12px;color:var(--muted)}
.popp{font-family:var(--mono);font-weight:600;font-size:15px;margin-top:4px}
.popblock{color:var(--rust);font-weight:600}
/* controls */
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 18px}
.chip{font-family:var(--mono);font-size:12px;border:1px solid var(--line);background:var(--surface);padding:6px 12px;border-radius:99px;cursor:pointer;user-select:none}
.chip[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip:focus-visible{outline:2px solid var(--teal);outline-offset:2px}
.spacer{flex:1}
.export{font-family:var(--mono);font-size:12px;font-weight:500;text-decoration:none;color:var(--paper);background:var(--teal-deep);padding:7px 13px;border-radius:8px;border:none;cursor:pointer}
.export:hover{background:var(--ink)}
/* cards */
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:12px;scroll-margin-top:16px}
.card.is-new{border-color:var(--teal)}
.card.flash{animation:flash 1.4s ease}
@keyframes flash{0%{box-shadow:0 0 0 3px var(--teal)}100%{box-shadow:0 8px 24px rgba(22,33,31,.05)}}
.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
.ptitle{font-family:var(--disp);font-weight:600;font-size:18px;margin:0 0 4px}
.loc{font-family:var(--mono);font-size:12px;color:var(--muted)}
.price{font-family:var(--mono);font-weight:600;font-size:20px;white-space:nowrap;text-align:right}
.quote{margin:12px 0 4px;padding:0 0 0 12px;border-left:3px solid var(--teal);font-size:14.5px;color:var(--ink)}
.warn{margin:8px 0 0;font-size:13px;color:var(--rust)}
.summary{color:var(--muted);margin:8px 0 0;font-size:15px}
.price small{display:block;font-weight:400;font-size:11px;color:var(--muted)}
.facts{display:flex;gap:18px;flex-wrap:wrap;margin:12px 0;font-family:var(--mono);font-size:13px}
.facts span{color:var(--muted)}
.badges{display:flex;gap:8px;flex-wrap:wrap}
.badge{font-family:var(--mono);font-size:11px;padding:4px 9px;border-radius:6px;border:1px solid transparent;white-space:nowrap}
.b-flag{background:#fbeceb;color:var(--flag);border-color:#f3cfcc}
.b-rule{background:#e7f2ee;color:var(--teal-deep);border-color:#c9e4db}
.b-llm{background:#eef1f0;color:var(--muted);border-color:var(--line)}
.b-existing{background:#e8f4ee;color:var(--pine);border-color:#cbe7d8}
.b-amber{background:#fbf1dd;color:var(--amber);border-color:#f0dcb4}
.b-rust{background:#fbe9e5;color:var(--rust);border-color:#f2d0c8}
.b-info{background:#eaf0f0;color:var(--teal-deep);border-color:#d3e2e1}
.b-open{background:#dff3ea;color:#0d6b46;border-color:#b7e3cd;font-weight:600}
.b-agree{background:#e7f2ee;color:var(--pine);border-color:#c9e4db}
.snip{border-left:2px solid var(--line);padding:2px 0 2px 12px;margin:10px 0;color:var(--muted);font-size:13.5px;font-style:italic}
.snip b{font-style:normal;color:var(--ink);background:#f0f4d8;padding:0 2px}
.open{display:inline-block;margin-top:12px!important;font-family:var(--mono);font-size:12px;text-decoration:none;color:var(--paper);background:var(--teal-deep);padding:8px 14px;border-radius:8px;margin-top:4px}
.seclabel{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin:30px 0 14px}
.empty{font-family:var(--mono);font-size:13px;color:var(--muted);padding:40px 20px;border:1px dashed var(--line);border-radius:10px;text-align:center}
footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);font-size:12.5px;color:var(--muted)}
@media (max-width:560px){h1{font-size:26px}.price{font-size:18px}.top{flex-direction:column}.price{text-align:left}#map{height:60vh}}
@media (prefers-reduced-motion:reduce){.card.flash{animation:none}}
</style>"""

LEAFLET_HEAD = (
    '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" '
    'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">'
    '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" '
    'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>'
)


def _page_js(points, csv_text):
    pts = json.dumps(points)
    csv_js = json.dumps(csv_text)
    return """
<script>
var POINTS=__POINTS__;
var CSV=__CSV__;
// tabs
document.querySelectorAll('.tab').forEach(function(t){
  t.addEventListener('click',function(){
    if(t.dataset.soon==='1') return;
    document.querySelectorAll('.tab').forEach(function(x){x.setAttribute('aria-selected',x===t?'true':'false');});
    document.querySelectorAll('.panel').forEach(function(p){p.classList.toggle('active',p.id===t.dataset.panel);});
    if(t.dataset.panel==='panel-map' && window._map){setTimeout(function(){window._map.invalidateSize();},50);}
  });
});
// map
(function(){
  if(typeof L==='undefined'){return;}
  var map=L.map('map',{scrollWheelZoom:false}).setView([46.5,8.0],8);
  window._map=map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
    maxZoom:18, attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
  if(POINTS.length){
    var group=[];
    POINTS.forEach(function(p){
      var m=L.circleMarker([p.lat,p.lon],{radius:8,color:'#fff',weight:1.5,
        fillColor:p.color,fillOpacity:0.9});
      var block=p.blocked?'<div class="popblock">closed to non-resident foreign buyers</div>':'';
      var pct=p.pct?(' &middot; '+p.pct+' second homes'):'';
      m.bindPopup('<p class="popt">'+p.title+'</p><div class="popm">'+p.muni+pct+'</div>'+
        '<div class="popp">'+p.price+' CHF &middot; '+p.rooms+' rm</div>'+block+
        '<div style="margin-top:6px"><a href="#card-'+p.id+'" class="popm" onclick="showCard(\\''+p.id+'\\')">view card</a> &middot; '+
        '<a href="'+p.url+'" target="_blank" rel="noopener" class="popm">open listing</a></div>');
      m.addTo(map); group.push([p.lat,p.lon]);
    });
    map.fitBounds(group,{padding:[40,40],maxZoom:11});
  }
})();
window.showCard=function(id){
  document.querySelector('[data-panel="panel-list"]').click();
  var el=document.getElementById('card-'+id);
  if(el){el.scrollIntoView({behavior:'smooth',block:'center'});el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');}
};
// list filters
var state={new:false,existing:false,cantons:new Set()};
function applyFilters(){document.querySelectorAll('.card').forEach(function(c){var ok=true;
  if(state.new&&!c.classList.contains('is-new'))ok=false;
  if(state.existing&&!c.classList.contains('s-existing'))ok=false;
  if(state.cantons.size&&!state.cantons.has(c.dataset.canton))ok=false;
  c.style.display=ok?'':'none';});}
var ctrl=document.getElementById('controls');
if(ctrl){ctrl.addEventListener('click',function(e){
  var chip=e.target.closest('.chip');if(!chip)return;
  var p=chip.getAttribute('aria-pressed')==='true';chip.setAttribute('aria-pressed',String(!p));
  if(chip.dataset.filter==='new')state.new=!p;
  else if(chip.dataset.filter==='existing')state.existing=!p;
  else if(chip.dataset.canton){if(p)state.cantons.delete(chip.dataset.canton);else state.cantons.add(chip.dataset.canton);}
  applyFilters();});}
// CSV export
var btn=document.getElementById('exportCsv');
if(btn){btn.addEventListener('click',function(){
  var blob=new Blob([CSV],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='foreign_eligible_listings.csv';document.body.appendChild(a);a.click();a.remove();});}
</script>""".replace("__POINTS__", pts).replace("__CSV__", csv_js)


FOOTER = """<footer>
<p>Each listing is included because its own text says a non-resident foreigner may buy; the quote shows the wording. Map pin colors: green resale, amber managed rental or unstated new build, rust new primary residence, grey closed to foreign buyers. Always confirm with a Swiss notary.</p>
</footer>"""


SOURCE_LABELS = {"flatfox": "Flatfox listings", "apify": "Homegate listings",
                 "mock": "sample listings"}


def _badge_date(run_ts) -> str:
    """Format the run timestamp as a short human date, e.g. 3 Oct 2026."""
    try:
        d = datetime.fromisoformat(str(run_ts).replace("Z", "+00:00"))
        return f"{d.day} {d:%b %Y}"
    except ValueError:
        return str(run_ts)[:10]


def render_report(cache: dict, cantons_swept, run_ts, processed, out_path, coords=None,
                  source=""):
    coords = coords or {}
    rows = [r for r in cache.values() if r.get("eligible") is True]
    rows.sort(key=lambda r: r.get("first_seen", ""), reverse=True)

    cards = [card_html(r, r.get("first_seen") == run_ts) for r in rows]

    cantons_present = sorted({r.get("canton", "") for r in rows if r.get("canton")})
    chips = "".join(f'<span class="chip" data-canton="{esc(c)}" aria-pressed="false">{esc(c)}</span>'
                    for c in cantons_present)

    body_cards = "\n".join(cards) if cards else '<div class="empty">No eligible listings yet.</div>'
    map_panel = '<section id="panel-map" class="panel active"><div id="map"></div></section>'
    list_panel = (
        '<section id="panel-list" class="panel">'
        '<div class="controls" id="controls">' + chips +
        '<span class="spacer"></span><button class="export" id="exportCsv">Download CSV</button></div>'
        + body_cards + '</section>'
    )
    summary = (f'<p class="summary">{len(rows)} holiday homes a non-resident foreigner can buy, '
               f'from {esc(SOURCE_LABELS.get(source, "listings"))} across {len(cantons_swept)} cantons.</p>')

    tabs = (
        '<div class="tabs" role="tablist">'
        '<button class="tab" role="tab" aria-selected="true" data-panel="panel-map">Map</button>'
        '<button class="tab" role="tab" aria-selected="false" data-panel="panel-list">Listings</button>'
        '</div>'
    )

    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Foreign-Eligible Property Ledger</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
        + LEAFLET_HEAD + REPORT_CSS +
        '</head><body><div class="wrap">'
        f'<header><p class="updated">Updated <time datetime="{esc(run_ts)}">{esc(_badge_date(run_ts))}</time> &middot; refreshed monthly</p>'
        '<h1>Foreign-Eligible Property Ledger</h1>' + summary + '</header>'
        + tabs + map_panel + list_panel + FOOTER +
        '</div>' + _page_js(_map_points(rows, coords), _csv_text(rows)) +
        '</body></html>'
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out_path, _csv_text(rows)
