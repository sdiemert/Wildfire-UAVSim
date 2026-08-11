#!/usr/bin/env python3
"""Generates the tables and charts of wind-report.html from summary.json.

The report has 73 arms in it. Transcribing that many numbers into HTML by hand is a way
of introducing an error that no amount of proofreading finds, so the fragments are generated here and
pasted in, and regenerating them after a re-run is a diff rather than a re-read.

    python3 experiments/20260810_wind/figures.py table cardinal
    python3 experiments/20260810_wind/figures.py chart cardinal
    python3 experiments/20260810_wind/figures.py all > fragments.html

The charts are inline SVG with no script and no external reference, because the document they go into is
printed to PDF. MU is plotted on an evenly spaced categorical axis rather than a linear one: the levels
themselves are not evenly spaced -- there are four below 0.85 and six above it, on purpose -- and a linear
axis would compress the entire interesting region into the last twentieth of the width. The caption says
so wherever a chart appears.
"""

# python libraries

import json
import pathlib
import sys

from itertools import groupby

HERE = pathlib.Path(__file__).resolve().parent

# one colour per direction, dark enough to survive a monochrome printer as distinct greys
COLOURS = {
    "north": "#1f6f8b", "south": "#b4441f", "east": "#3f7a2e", "west": "#6a4b9c",
    "north+east": "#1f6f8b", "north+west": "#6a4b9c", "south+east": "#b4441f", "south+west": "#3f7a2e",
    "50": "#1f6f8b", "100": "#b4441f", "200": "#3f7a2e", "400": "#6a4b9c",
    "0.95": "#1f6f8b", "1.0": "#b4441f",
}

# geometry of a chart, in the SVG's own user units
WIDTH, HEIGHT = 720, 300
LEFT, RIGHT, TOP, BOTTOM = 52, 132, 18, 44


def load():
    path = HERE / "summary.json"
    if not path.exists():
        raise SystemExit("summary.json is missing -- run experiments/20260810_wind/analyse.py first")
    return json.loads(path.read_text())


# --- shaping ----------------------------------------------------------------


# Turns one sweep's flat list of arms into {series name: {x value: row}}, plus the ordered x values. The
# series is what gets a line and a colour; the x value is what runs along the bottom.
def series_of(rows, series_key, x_key):
    series, xs = {}, []
    for row in rows:
        name = series_key(row)
        x = str(row[x_key])
        if x not in xs:
            xs.append(x)
        series.setdefault(name, {})[x] = row
    xs.sort(key=float)

    # a deliberate order rather than whatever the rows arrived in: the two directions that share a long
    # upwind approach to the base belong next to each other in the legend, and numeric series belong in
    # numeric order
    def rank(name):
        if name in ORDER:
            return (0, ORDER.index(name))
        try:
            return (1, float(name))
        except ValueError:
            return (2, name)

    return {name: series[name] for name in sorted(series, key=rank)}, xs


# north and east approach the base across 25 cells, south and west across 73; pairing them in the legend
# is what makes the two-band shape of the cardinal chart legible
ORDER = ["south", "west", "north", "east",
         "south+east", "south+west", "north+east", "north+west"]


SHAPES = {
    "cardinal": (lambda row: row["direction"], "mu"),
    "diagonal": (lambda row: f"{row['first_dir']}+{row['second_dir']}", "mu"),
    "runlength": (lambda row: str(row["batch_size"]), "mu"),
    "steadiness": (lambda row: str(row["mu"]), "first_dir_prob"),
}


# --- tables -----------------------------------------------------------------


def table(summary, name):
    series, xs = series_of(summary[name], *SHAPES[name])
    names = list(series)

    axis_label = {"cardinal": "MU", "diagonal": "MU", "runlength": "MU",
                  "steadiness": "FIRST_DIR_PROB"}[name]

    out = ['<table class="tight">', "<thead>", "<tr>",
           f'<th rowspan="2">{axis_label}</th>']
    for series_name in names:
        out.append(f'<th colspan="2" class="num">{series_name}</th>')
    out.append("</tr>\n<tr>")
    for _ in names:
        out.append('<th class="num">loss</th><th class="num">95% Wilson</th>')
    out.append("</tr>\n</thead>\n<tbody>")

    for x in xs:
        # the rows where something is actually happening get the accent, so that the flat region above
        # them reads as the finding it is rather than as filler
        moved = any(series[n][x]["rate"] < 99.0 for n in names if x in series[n])
        opening = '<tr class="mark">' if moved else "<tr>"
        out.append(f"{opening}<th>{x}</th>")
        for series_name in names:
            row = series[series_name].get(x)
            if row is None:
                out.append('<td class="num">&ndash;</td><td class="ci">&ndash;</td>')
                continue
            out.append(f'<td class="num">{row["rate"]:.1f}%</td>'
                       f'<td class="ci">{row["low"]:.1f}&ndash;{row["high"]:.1f}</td>')
        out.append("</tr>")
    out.append("</tbody>\n</table>")
    return "\n".join(out)


# --- charts -----------------------------------------------------------------


def chart(summary, name):
    series, xs = series_of(summary[name], *SHAPES[name])

    def px(index):
        if len(xs) == 1:
            return (LEFT + WIDTH - RIGHT) / 2
        return LEFT + index * (WIDTH - LEFT - RIGHT) / (len(xs) - 1)

    def py(rate):
        return TOP + (100.0 - rate) * (HEIGHT - TOP - BOTTOM) / 100.0

    out = [f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
           f'aria-label="loss rate against wind strength" style="width:100%;height:auto">',
           '<g font-family="ui-monospace, Menlo, monospace" font-size="10">']

    # horizontal rules at every 25 points, and the axis labels on them
    for rate in (0, 25, 50, 75, 100):
        y = py(rate)
        out.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{WIDTH - RIGHT}" y2="{y:.1f}" '
                   f'stroke="#d8dedd" stroke-width="1"/>')
        out.append(f'<text x="{LEFT - 8}" y="{y + 3.5:.1f}" text-anchor="end" fill="#6b7a77">{rate}%</text>')

    # the x axis: one tick per level, labelled with the level itself
    for index, x in enumerate(xs):
        out.append(f'<text x="{px(index):.1f}" y="{HEIGHT - BOTTOM + 18:.0f}" text-anchor="middle" '
                   f'fill="#6b7a77">{x}</text>')

    ends = []
    for series_name, points in series.items():
        colour = COLOURS.get(series_name, "#14201e")
        drawn = [(px(index), py(points[x]["rate"])) for index, x in enumerate(xs) if x in points]
        path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(drawn))
        out.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2"/>')
        for x, y in drawn:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{colour}"/>')
        # A series that stops short of the right hand edge has no margin to put its name in, and at the
        # point it stops it is usually still lying on top of every other curve. Drop its label below the
        # line instead, into the space the curves have not reached yet.
        truncated = len(drawn) < len(xs)
        ends.append({"x": drawn[-1][0], "y": drawn[-1][1],
                     "label_y": drawn[-1][1] + (18 if truncated else 0),
                     "colour": colour, "name": series_name, "truncated": truncated})

    # The legend sits at the right hand end of each line rather than in a box, so that a reader tracing a
    # curve never has to look away from it. Where the curves converge -- and at MU = 1 all four of them
    # land within two points of each other -- the labels would print on top of one another, so they are
    # pushed apart and a leader line runs back to the point each one belongs to.
    # Only labels that end at the same place can collide, and not every series reaches the right hand
    # edge -- an incomplete sweep leaves one stopping half way across, and staggering it against curves it
    # does not touch would move it on top of the ones it does.
    for _, group in groupby(sorted(ends, key=lambda end: (end["x"], end["y"])),
                            key=lambda end: end["x"]):
        column = list(group)
        for previous, end in zip(column, column[1:]):
            end["label_y"] = max(end["label_y"], previous["label_y"] + 12)

        # pushing down can run the last label off the bottom of the plot and into the axis ticks, so if
        # it does, shift the whole stack back up and settle it against the top instead
        overflow = column[-1]["label_y"] - (HEIGHT - BOTTOM)
        if overflow > 0:
            for end in column:
                end["label_y"] -= overflow
            for previous, end in zip(reversed(column[1:]), reversed(column[:-1])):
                end["label_y"] = min(end["label_y"], previous["label_y"] - 12)
            for end in column:
                end["label_y"] = max(end["label_y"], TOP)
    for end in ends:
        if abs(end["label_y"] - end["y"]) > 1:
            out.append(f'<line x1="{end["x"] + 3:.1f}" y1="{end["y"]:.1f}" '
                       f'x2="{end["x"] + 7:.1f}" y2="{end["label_y"]:.1f}" '
                       f'stroke="{end["colour"]}" stroke-width="0.75"/>')
        anchor = ' text-anchor="middle"' if end["truncated"] else ""
        offset = 0 if end["truncated"] else 9
        out.append(f'<text x="{end["x"] + offset:.1f}" y="{end["label_y"] + 3.5:.1f}"{anchor} '
                   f'fill="{end["colour"]}">{end["name"]}</text>')

    out.append("</g>\n</svg>")
    return "\n".join(out)


# --- main -------------------------------------------------------------------


def main():
    summary = load()
    what = sys.argv[1] if len(sys.argv) > 1 else "all"

    if what == "all":
        for name in SHAPES:
            if name not in summary:
                continue
            print(f"<!-- ===== {name} ===== -->")
            print(chart(summary, name))
            print(table(summary, name))
            print()
        return

    name = sys.argv[2]
    print({"table": table, "chart": chart}[what](summary, name))


if __name__ == "__main__":
    main()
