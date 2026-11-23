"""Troubleshooting guides generated from catalog/troubleshooting.yaml, the theme and the
models' own `troubleshooting` entries:

    fsf docs troubleshooting      ->  build/docs/troubleshooting/

    index.html                 every status, symptom and part
    status-<status>.html       one page per hub status
    symptoms.html, parts.html
    troubleshooting.md         the same content for an LLM agent or a text reader

The dashboard serves the same entries on its help page, so the LED legend, a banner on the
dashboard and a row in the log all lead to the same words.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import yaml

from .builddocs import _page
from .catalog import Catalog, ConfigError

QUIET = {"ok", "idle"}      # statuses that need no guide


def load(catalog: Catalog, theme_id: str = "default") -> dict:
    """The validated troubleshooting file. Every status of the theme must have an entry."""
    path = catalog.root / "catalog" / "troubleshooting.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = catalog.schemas.check("Troubleshooting", doc, "catalog/troubleshooting.yaml")
    if not problems:
        theme = catalog.get("Theme", theme_id)
        for status in theme["priority"]:
            if status not in QUIET and status not in doc["statuses"]:
                problems.append(f"catalog/troubleshooting.yaml: no entry for status {status!r}")
        for status in doc["statuses"]:
            if status not in theme["statuses"]:
                problems.append(f"catalog/troubleshooting.yaml: {status!r} is not a status of theme {theme_id}")
        for entry in doc["symptoms"]:
            for status in entry["statuses"]:
                if status not in doc["statuses"]:
                    problems.append(f"catalog/troubleshooting.yaml: symptom {entry['symptom']!r} names unknown status {status!r}")
            for part in entry["parts"]:
                if part not in catalog.items["Model"]:
                    problems.append(f"catalog/troubleshooting.yaml: symptom {entry['symptom']!r} names unknown model {part!r}")
    if problems:
        raise ConfigError(problems)
    return doc


def for_status(catalog: Catalog, status: str, theme_id: str = "default") -> dict | None:
    """Everything known about one status: its label and meaning, the guide, related symptoms."""
    doc = load(catalog, theme_id)
    guide = doc["statuses"].get(status)
    if guide is None:
        return None
    style = catalog.get("Theme", theme_id)["statuses"][status]
    return {"status": status, "label": style.get("label", status), "meaning": style.get("meaning", ""), **guide,
            "symptoms": [s for s in doc["symptoms"] if status in s["statuses"]]}


def _list(items: list[str], ordered: bool = True) -> str:
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{escape(i)}</li>" for i in items) + f"</{tag}>"


def _status_html(entry: dict) -> str:
    body = [f'<p><a href="index.html">← All troubleshooting</a></p><h1>{escape(entry["label"])}</h1>',
            f'<p class="muted">Status <code>{escape(entry["status"])}</code>. {escape(entry["meaning"])}</p>',
            f"<h2>What the hub is doing</h2><p>{escape(entry['doing'])}</p>",
            "<h2>Likely causes, most likely first</h2>" + _list(entry["causes"]),
            "<h2>What to check, in this order</h2>" + _list(entry["checks"]),
            f"<h2>When it clears</h2><p>{escape(entry['clears'])}</p>"]
    if entry["symptoms"]:
        links = "".join(f'<li><a href="symptoms.html#{i}">{escape(s["symptom"])}</a></li>' for i, s in entry["symptoms_at"])
        body.append(f"<h2>Does it look like this?</h2><ul>{links}</ul>")
    return _page(f"{entry['label']}: troubleshooting", "\n".join(body))


def build(catalog: Catalog, out_dir: Path, theme_id: str = "default") -> list[Path]:
    doc = load(catalog, theme_id)
    theme = catalog.get("Theme", theme_id)
    statuses = [s for s in theme["priority"] if s in doc["statuses"]]
    files: dict[str, str] = {}

    for status in statuses:
        entry = for_status(catalog, status, theme_id)
        entry["symptoms_at"] = [(i, s) for i, s in enumerate(doc["symptoms"]) if status in s["statuses"]]
        files[f"status-{status}.html"] = _status_html(entry)

    symptom_html = ['<p><a href="index.html">← All troubleshooting</a></p><h1>By symptom</h1>']
    for i, entry in enumerate(doc["symptoms"]):
        related = ", ".join(f'<a href="status-{s}.html">{escape(theme["statuses"][s].get("label", s))}</a>' for s in entry["statuses"])
        symptom_html.append(f'<h2 id="{i}">{escape(entry["symptom"])}</h2>'
                            + (f'<p class="muted">Usually shows as: {related}</p>' if related else "")
                            + "<h3>Likely causes</h3>" + _list(entry["causes"]) + "<h3>What to check</h3>" + _list(entry["checks"]))
    files["symptoms.html"] = _page("Troubleshooting by symptom", "\n".join(symptom_html))

    part_html = ['<p><a href="index.html">← All troubleshooting</a></p><h1>By part</h1>']
    with_guides = [m for m in sorted(catalog.items["Model"].values(), key=lambda m: m.get("name", m["id"])) if m.get("troubleshooting")]
    for model in with_guides:
        part_html.append(f'<h2 id="{escape(model["id"])}">{escape(model.get("name", model["id"]))}</h2>')
        if model.get("datasheet_checked") is False:
            part_html.append('<p class="warn">From general experience with this part; not yet confirmed on a bench.</p>')
        for item in model["troubleshooting"]:
            part_html.append(f"<h3>{escape(item['symptom'])}</h3><p class='muted'>Causes</p>" + _list(item["causes"], ordered=False)
                             + "<p class='muted'>Checks</p>" + _list(item["checks"]))
    files["parts.html"] = _page("Troubleshooting by part", "\n".join(part_html))

    index = ["<h1>Troubleshooting</h1>",
             '<p class="muted">Start from what you see: the colour on the strip, the status on the dashboard, or what is going wrong.</p>',
             "<h2>By status</h2><ul>" + "".join(
                 f'<li><a href="status-{s}.html">{escape(theme["statuses"][s].get("label", s))}</a> '
                 f'<span class="muted">{escape(theme["statuses"][s].get("meaning", ""))}</span></li>' for s in statuses) + "</ul>",
             '<h2>By symptom</h2><ul>' + "".join(f'<li><a href="symptoms.html#{i}">{escape(s["symptom"])}</a></li>'
                                                 for i, s in enumerate(doc["symptoms"])) + "</ul>",
             '<h2>By part</h2><ul>' + "".join(f'<li><a href="parts.html#{escape(m["id"])}">{escape(m.get("name", m["id"]))}</a></li>'
                                              for m in with_guides) + "</ul>"]
    files["index.html"] = _page("Troubleshooting", "\n".join(index))

    md = ["# Troubleshooting", "", "Generated from catalog/troubleshooting.yaml, the theme and the models. Do not edit.", "",
          "## By status", ""]
    for status in statuses:
        entry = doc["statuses"][status]
        style = theme["statuses"][status]
        md += [f"### {style.get('label', status)} (`{status}`)", "", style.get("meaning", ""), "",
               f"The hub: {entry['doing']}", "", "Likely causes, most likely first:", *[f"{i}. {c}" for i, c in enumerate(entry["causes"], 1)], "",
               "Checks, in order:", *[f"{i}. {c}" for i, c in enumerate(entry["checks"], 1)], "", f"Clears: {entry['clears']}", ""]
    md += ["## By symptom", ""]
    for entry in doc["symptoms"]:
        md += [f"### {entry['symptom']}", "", "Causes:", *[f"- {c}" for c in entry["causes"]], "", "Checks:",
               *[f"{i}. {c}" for i, c in enumerate(entry["checks"], 1)], ""]
    md += ["## By part", ""]
    for model in with_guides:
        md += [f"### {model.get('name', model['id'])} (`{model['id']}`)", ""]
        for item in model["troubleshooting"]:
            md += [f"**{item['symptom']}**", "", "Causes: " + "; ".join(item["causes"]) + ".", "",
                   *[f"{i}. {c}" for i, c in enumerate(item["checks"], 1)], ""]
    files["troubleshooting.md"] = "\n".join(md)

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written
