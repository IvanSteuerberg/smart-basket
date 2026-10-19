"""Generate the OSF project index (wiki "home") from the live file listing.

Dates, versions and links come from OSF; descriptions, statuses and pending
work come from scripts/osf_index.json.

Usage:
    python scripts/osf_index.py            # print the generated markdown
    python scripts/osf_index.py --apply    # save it as a new version of the wiki home page
"""
import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from osf_publish import API, NODE, ROOT, Osf, load_token  # noqa: E402

CONFIG = pathlib.Path(__file__).resolve().parent / "osf_index.json"

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:  # tzdata missing on some Windows installs
    TZ = datetime.timezone(datetime.timedelta(hours=1))


def day(timestamp):
    value = datetime.datetime.fromisoformat(timestamp.replace("Z", ""))
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(TZ).strftime("%d/%m/%Y")


def count_versions(osf, item):
    url, total = item["relationships"]["versions"]["links"]["related"]["href"], 0
    while url:
        page = osf.request(url)
        total += len(page["data"])
        url = page["links"].get("next")
    return total


def note_date(name):
    """Class notes are named dd-mm-yyyy.txt; sort them chronologically."""
    try:
        return datetime.datetime.strptime(name.split(".")[0], "%d-%m-%Y")
    except ValueError:
        return datetime.datetime.max


def build(osf, config):
    root = osf.root()
    top = osf.list_folder(root["relationships"]["files"]["links"]["related"]["href"])
    lines = [
        f"# {config['title']}",
        "",
        config["subtitle"],
        "",
        f"Código y base de conocimiento del proyecto: {config['repository']}",
        "",
        f"*Índice generado automáticamente el {datetime.datetime.now(TZ).strftime('%d/%m/%Y')} "
        "a partir de los archivos del proyecto. Cada documento conserva su historial de versiones en OSF.*",
        "",
    ]
    for folder in sorted(name for name, item in top.items() if item["attributes"]["kind"] == "folder"):
        entity = top[folder]
        files = osf.list_folder(entity["relationships"]["files"]["links"]["related"]["href"])
        lines += [f"## {folder}", "", config["folders"].get(folder, ""), ""]
        if not files:
            lines += [config.get("empty_notes", {}).get(folder, "*Vacía.*"), ""]
            continue
        if folder in config.get("list_only", []):
            for name in sorted(files, key=note_date):
                item = files[name]
                lines.append(f"* [{name}]({item['links']['html']}) · subida el {day(item['attributes']['date_created'])}")
            lines.append("")
            continue
        lines += ["| Documento | Descripción | Estado | Creado | Última versión | Versiones |",
                  "|---|---|---|---|---|---|"]
        for name in sorted(files):
            item = files[name]
            attrs = item["attributes"]
            description, status = config["files"].get(f"{folder}/{name}", ["", ""])
            if attrs["kind"] == "folder":
                lines.append(f"| {name}/ | {description} | {status} | | | |")
                continue
            versions = count_versions(osf, item)
            lines.append(f"| [{name}]({item['links']['html']}) | {description} | {status} | "
                         f"{day(attrs['date_created'])} | {day(attrs['date_modified'])} | {versions} |")
        lines.append("")
    if config.get("pending"):
        lines += ["## Pendiente", ""] + [f"* {item}" for item in config["pending"]] + [""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="save the index to the wiki")
    args = parser.parse_args()

    osf = Osf(load_token())
    content = build(osf, json.loads(CONFIG.read_text(encoding="utf-8")))
    if not args.apply:
        sys.stdout.reconfigure(encoding="utf-8")
        print(content)
        return
    wikis = osf.request(f"{API}/nodes/{NODE}/wikis/")["data"]
    home = next(w for w in wikis if w["attributes"]["name"].lower() == "home")
    body = json.dumps({"data": {"type": "wiki-versions", "attributes": {"content": content}}}).encode("utf-8")
    osf.headers["Content-Type"] = "application/vnd.api+json"
    osf.request(f"{API}/wikis/{home['id']}/versions/", method="POST", data=body)
    print(f"Wiki home updated ({len(content)} characters).")


if __name__ == "__main__":
    main()
