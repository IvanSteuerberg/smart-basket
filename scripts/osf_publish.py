"""Compile the academic LaTeX documents and publish their PDFs to OSF Storage.

Each document is always uploaded under the same name, so OSF keeps the full
version history and no dated copies are needed. PDFs are built reproducibly
(timestamps pinned to the last git commit that touched the document), so an
unchanged document produces the same bytes and is not uploaded again.

Usage:
    python scripts/osf_publish.py            # dry run: show what would change
    python scripts/osf_publish.py --apply    # compile and upload

Requires OSF_TOKEN in the environment or in the repo's .env file, with the
osf.full_write scope for --apply.
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

NODE = "ysmkz"
API = "https://api.osf.io/v2"
ROOT = pathlib.Path(__file__).resolve().parent.parent

# (source folder, main .tex file, OSF folder, published file name)
DOCUMENTS = [
    ("docs/idea-base", "idea.tex", "01-proyecto", "Concepto_del_proyecto.pdf"),
    ("docs/memoria-prompts", "memoria-prompts.tex", "01-proyecto", "Memoria_Prompts.pdf"),
    ("docs/registro-actividad", "registro-actividad.tex", "01-proyecto", "Registro_Actividad.pdf"),
]


def load_token():
    token = os.environ.get("OSF_TOKEN")
    env_file = ROOT / ".env"
    if not token and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "OSF_TOKEN":
                token = value.strip().strip("'\"")
    if not token:
        sys.exit("OSF_TOKEN not found in the environment or .env")
    return token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Osf:
    def __init__(self, token):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.opener = urllib.request.build_opener(_NoRedirect)

    def request(self, url, method="GET", data=None):
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        try:
            with self.opener.open(req, timeout=120) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            # Downloads redirect to external storage, which rejects our auth header.
            if e.code in (301, 302, 303, 307, 308):
                with urllib.request.urlopen(e.headers["Location"], timeout=120) as resp:
                    return resp.read()
            raise RuntimeError(f"{method} {url} -> HTTP {e.code}: {e.read()[:300]!r}") from None
        return json.loads(body) if body else None

    def list_folder(self, url):
        items = []
        while url:
            page = self.request(url)
            items.extend(page["data"])
            url = page["links"].get("next")
        return {item["attributes"]["name"]: item for item in items}

    def root(self):
        providers = self.request(f"{API}/nodes/{NODE}/files/")["data"]
        return next(p for p in providers if p["attributes"]["provider"] == "osfstorage")


def compile_pdf(folder, tex):
    src = ROOT / folder
    epoch = subprocess.run(["git", "log", "-1", "--format=%ct", "--", folder], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    env = dict(os.environ, FORCE_SOURCE_DATE="1")
    # Uncommitted changes get the current time, so they always count as new.
    dirty = subprocess.run(["git", "status", "--porcelain", "--", folder], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    if epoch and not dirty:
        env["SOURCE_DATE_EPOCH"] = epoch
    subprocess.run(["latexmk", "-pdf", "-g", "-interaction=nonstopmode", "-halt-on-error", tex],
                   cwd=src, env=env, check=True, capture_output=True)
    return src / tex.replace(".tex", ".pdf"), bool(dirty)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="upload instead of dry run")
    args = parser.parse_args()

    osf = Osf(load_token())
    root = osf.root()
    root_items = osf.list_folder(root["relationships"]["files"]["links"]["related"]["href"])
    folders = {}

    for folder, tex, remote_folder, name in DOCUMENTS:
        pdf, dirty = compile_pdf(folder, tex)
        local_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
        note = " (uncommitted changes)" if dirty else ""

        if remote_folder not in folders:
            entity = root_items.get(remote_folder)
            if entity is None:
                print(f"create folder /{remote_folder}/")
                if not args.apply:
                    folders[remote_folder] = None
                    print(f"upload  /{remote_folder}/{name}{note}")
                    continue
                entity = osf.request(f"{root['links']['new_folder']}&name={remote_folder}", method="PUT")["data"]
                entity = {"attributes": entity["attributes"], "links": entity["links"],
                          "relationships": {"files": {"links": {"related": {"href":
                              f"{API}/nodes/{NODE}/files/osfstorage{entity['attributes']['path']}"}}}}}
            folders[remote_folder] = (entity, osf.list_folder(entity["relationships"]["files"]["links"]["related"]["href"]))

        if folders[remote_folder] is None:
            print(f"upload  /{remote_folder}/{name}{note}")
            continue
        entity, children = folders[remote_folder]
        existing = children.get(name)
        if existing and existing["attributes"]["extra"]["hashes"]["sha256"] == local_hash:
            print(f"same    /{remote_folder}/{name}")
            continue
        action = "update" if existing else "upload"
        print(f"{action:7} /{remote_folder}/{name}{note}")
        if args.apply:
            url = (f"{existing['links']['upload']}?kind=file" if existing
                   else f"{entity['links']['upload']}?kind=file&name={name}")
            osf.request(url, method="PUT", data=pdf.read_bytes())

    if not args.apply:
        print("\nDry run: nothing uploaded. Use --apply to publish.")


if __name__ == "__main__":
    main()
