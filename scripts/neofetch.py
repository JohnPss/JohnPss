#!/usr/bin/env python3
"""Render a neofetch-style profile card (dark + light SVG) with live GitHub stats.

Usage: GITHUB_TOKEN=... USERNAME=JohnPss python scripts/neofetch.py avatar.png dist/
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

TOKEN = os.environ["GITHUB_TOKEN"]
USER = os.environ.get("USERNAME", "JohnPss")
WIDTH = 58  # characters in the info column

# --------------------------------------------------------------------------- #
# Static profile info: edit these freely                                     #
# --------------------------------------------------------------------------- #
PROFILE = [
    ("OS", "Ubuntu 24.04 LTS, Linux"),
    ("Uptime", "{uptime}"),
    ("Host", "CEFET-MG, Computer Engineering"),
    ("Location", "Divinópolis-MG, Brazil"),
    ("IDE", "VS Code"),
    None,
    ("Languages.Programming", "C++, C, Python, Java, R, TS"),
    ("Languages.Hardware", "VHDL (FPGA)"),
    ("Languages.Real", "Portuguese, English"),
    None,
    ("Building.Research", "NetCanDrug"),
    ("Building.Products", "BoraPelada, IntegraDerme"),
    ("Interests", "Algorithms, Bioinfo, DevOps"),
]
CONTACT = [
    ("Email", "joaopedrosilvasiqueira1@gmail.com"),
    ("LinkedIn", "in/joão-pedro-siqueira"),
    ("Discord", "johnpss"),
]

THEMES = {
    "dark": dict(bg="#0d1117", border="#30363d", text="#c9d1d9", key="#00bfbf",
                 dots="#484f58", art="#00a3a3", add="#3fb950", rem="#f85149"),
    "light": dict(bg="#f6f8fa", border="#d0d7de", text="#24292f", key="#007a7a",
                  dots="#afb8c1", art="#005f5f", add="#1a7f37", rem="#cf222e"),
}


# --------------------------------------------------------------------------- #
# GitHub API                                                                  #
# --------------------------------------------------------------------------- #
def _request(url: str, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "neofetch-profile",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


def graphql(query: str, **variables) -> dict:
    status, data = _request("https://api.github.com/graphql", {"query": query, "variables": variables})
    if status != 200 or "errors" in data:
        raise RuntimeError(f"GraphQL failed ({status}): {data}")
    return data["data"]


def fetch_stats() -> dict:
    user = graphql(
        """query($login: String!) {
          user(login: $login) {
            createdAt
            followers { totalCount }
            repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) { totalCount }
            repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
              totalCount
              nodes { name stargazerCount }
            }
          }
        }""",
        login=USER,
    )["user"]

    created = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)

    # Commits: contributionsCollection is limited to 1-year windows.
    commits, start = 0, created
    while start < now:
        end = min(start + dt.timedelta(days=365), now)
        c = graphql(
            """query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) { contributionsCollection(from: $from, to: $to) {
                totalCommitContributions restrictedContributionsCount } } }""",
            login=USER, **{"from": start.isoformat(), "to": end.isoformat()},
        )["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        start = end

    # Lines of code: sum of weekly additions/deletions authored by USER.
    added = deleted = 0
    for repo in user["repositories"]["nodes"]:
        url = f"https://api.github.com/repos/{USER}/{repo['name']}/stats/contributors"
        for _ in range(8):  # GitHub answers 202 while it computes the stats
            status, data = _request(url)
            if status == 200:
                break
            time.sleep(4)
        else:
            print(f"warn: no LOC stats for {repo['name']}", file=sys.stderr)
            continue
        for contrib in data or []:
            if (contrib.get("author") or {}).get("login", "").lower() == USER.lower():
                added += sum(w["a"] for w in contrib["weeks"])
                deleted += sum(w["d"] for w in contrib["weeks"])

    return dict(
        uptime=uptime(created.date(), now.date()),
        repos=user["repositories"]["totalCount"],
        contributed=user["repositoriesContributedTo"]["totalCount"],
        stars=sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        followers=user["followers"]["totalCount"],
        commits=commits,
        added=added,
        deleted=deleted,
    )


def uptime(start: dt.date, today: dt.date) -> str:
    years = today.year - start.year
    months = today.month - start.month
    days = today.day - start.day
    if days < 0:
        months -= 1
        prev_month_end = today.replace(day=1) - dt.timedelta(days=1)
        days += prev_month_end.day
    if months < 0:
        years -= 1
        months += 12
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{plural(years, 'year')}, {plural(months, 'month')}, {plural(days, 'day')}"


# --------------------------------------------------------------------------- #
# ASCII art                                                                   #
# --------------------------------------------------------------------------- #
def ascii_art(path: str, positive: bool, cols: int = 44) -> list[str]:
    """Background-masked ASCII portrait.

    positive=True  -> bright pixels get dense glyphs (for dark backgrounds)
    positive=False -> dark pixels get dense glyphs (for light backgrounds)
    """
    rgb = Image.open(path).convert("RGB")
    w, h = rgb.size
    rgb = rgb.crop((int(w * .25), int(h * .08), int(w * .82), int(h * .80)))  # head + shoulders
    rows = int(cols * rgb.height / rgb.width * 0.5)  # glyphs are ~2x taller than wide
    sat = rgb.convert("HSV").getchannel("S").filter(ImageFilter.MedianFilter(5)).resize((cols, rows), Image.BOX)
    raw = rgb.convert("L").resize((cols, rows), Image.BOX)
    lum = (rgb.convert("L").filter(ImageFilter.UnsharpMask(radius=2, percent=220, threshold=1))
           .resize((cols, rows), Image.LANCZOS))
    # The wall behind is grey (low saturation); skin is saturated, hair/shirt are dark.
    subject = [[sat.getpixel((x, y)) > 50 or raw.getpixel((x, y)) < 75 for x in range(cols)] for y in range(rows)]
    vals = sorted(lum.getpixel((x, y)) for y in range(rows) for x in range(cols) if subject[y][x])
    lo, hi = vals[int(len(vals) * .03)], vals[int(len(vals) * .97)]
    ramp = " .:-=+*#%@"
    out = []
    for y in range(rows):
        line = ""
        for x in range(cols):
            if not subject[y][x]:
                line += " "
                continue
            v = min(1.0, max(0.0, (lum.getpixel((x, y)) - lo) / max(1, hi - lo)))
            v = v if positive else 1 - v
            line += ramp[max(1, min(len(ramp) - 1, int(v ** 0.9 * len(ramp))))]
        out.append(line)
    return out


# --------------------------------------------------------------------------- #
# SVG                                                                         #
# --------------------------------------------------------------------------- #
def esc(s: str) -> str:
    return html.escape(s, quote=False)


def field(key: str, value: str, width: int = WIDTH) -> list[tuple[str, str]]:
    """'. Key: ...... value' as (css-class, text) segments, padded to width."""
    dots = max(1, width - len(key) - len(value) - 5)
    return [("dots", ". "), ("key", key), ("text", ":"), ("dots", " " + "." * dots + " "), ("text", value)]


def header(title: str, width: int = WIDTH) -> list[tuple[str, str]]:
    return [("text", f"- {title} "), ("dots", "-" * (width - len(title) - 3))]


def info_lines(s: dict) -> list[list[tuple[str, str]]]:
    lines: list[list[tuple[str, str]]] = [
        [("key", "joao"), ("text", "@"), ("key", "siqueira"), ("text", " "), ("dots", "-" * (WIDTH - 14))]
    ]
    for item in PROFILE:
        lines.append([] if item is None else field(item[0], item[1].format(**s)))
    lines += [[], header("Contact")]
    lines += [field(k, v) for k, v in CONTACT]
    lines += [[], header("GitHub Stats")]

    half = 33  # left half of the two-column stats rows
    left = field("Repos", f"{s['repos']} {{Contributed: {s['contributed']}}}", half)
    right = field("Stars", f"{s['stars']:,}", WIDTH - half - 1)[1:]
    lines.append(left + [("text", " | ")] + right)
    left = field("Commits", f"{s['commits']:,}", half)
    right = field("Followers", f"{s['followers']:,}", WIDTH - half - 1)[1:]
    lines.append(left + [("text", " | ")] + right)

    total = f"{s['added'] - s['deleted']:,}"
    add, rem = f"{s['added']:,}++", f"{s['deleted']:,}--"
    loc_value_len = len(total) + len(add) + len(rem) + 7
    dots = max(1, WIDTH - len("Lines of Code") - loc_value_len - 5)
    lines.append([("dots", ". "), ("key", "Lines of Code"), ("text", ":"),
                  ("dots", " " + "." * dots + " "), ("text", f"{total} ( "),
                  ("add", add), ("text", ", "), ("rem", rem), ("text", " )")])
    lines.append([("text", "$ "), ("cursor", "█")])
    return lines


def render(theme: dict, art: list[str], info: list[list[tuple[str, str]]]) -> str:
    fs, lh, cw = 14, 20, 8.43  # font size, line height, approx glyph width
    rows = max(len(art), len(info))
    art_top = (rows - len(art)) // 2
    art_x, info_x = 24, 24 + int(len(art[0]) * cw) + 28
    width = info_x + int(WIDTH * cw) + 24
    height = 30 + rows * lh + 20

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ConsolasFallback,Consolas,\'DejaVu Sans Mono\',monospace" '
        f'font-size="{fs}px">',
        "<style>",
        f".key{{fill:{theme['key']}}} .text{{fill:{theme['text']}}} .dots{{fill:{theme['dots']}}}",
        f".add{{fill:{theme['add']}}} .rem{{fill:{theme['rem']}}} .art{{fill:{theme['art']}}}",
        f".cursor{{fill:{theme['key']};animation:blink 1s step-end infinite}}",
        "@keyframes blink{50%{opacity:0}}",
        ".row{opacity:0;animation:in .35s ease-out forwards}",
        "@keyframes in{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:none}}",
        "@media (prefers-reduced-motion:reduce){.row,.cursor{animation:none;opacity:1}}",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="12" fill="{theme["bg"]}" stroke="{theme["border"]}"/>',
    ]
    for i, line in enumerate(art):
        y = 30 + (art_top + i) * lh
        out.append(f'<text x="{art_x}" y="{y}" class="art" xml:space="preserve">{esc(line)}</text>')
    for i, segs in enumerate(info):
        y = 30 + i * lh
        body = "".join(f'<tspan class="{c}">{esc(t)}</tspan>' for c, t in segs)
        out.append(f'<text x="{info_x}" y="{y}" class="row" style="animation-delay:{i * 0.04:.2f}s" '
                   f'xml:space="preserve">{body}</text>')
    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    avatar, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = fetch_stats()
    print(json.dumps(stats, indent=2))
    info = info_lines(stats)
    for name, theme in THEMES.items():
        art = ascii_art(avatar, positive=(name == "dark"))
        (out_dir / f"neofetch-{name}.svg").write_text(render(theme, art, info), encoding="utf-8")


if __name__ == "__main__":
    main()
