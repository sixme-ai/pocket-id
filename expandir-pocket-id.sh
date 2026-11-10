#!/usr/bin/env bash
# Expande o ZIP ja enviado ao branch dev e publica os arquivos na raiz.
set -Eeuo pipefail

erro() { printf 'ERRO: %s\n' "$*" >&2; exit 1; }
command -v git >/dev/null || erro "Git nao instalado."
command -v python3 >/dev/null || erro "Python 3 nao instalado."
raiz=$(git rev-parse --show-toplevel 2>/dev/null) || erro "Execute dentro do clone do repositorio."
cd "$raiz"

[[ "$(git branch --show-current)" == "dev" ]] || erro "Use a branch dev."
origem=$(git remote get-url origin) || erro "Remote origin ausente."
case "$origem" in
  https://github.com/sixme-ai/pocket-id|https://github.com/sixme-ai/pocket-id.git|git@github.com:sixme-ai/pocket-id.git|ssh://git@github.com/sixme-ai/pocket-id.git) ;;
  *) erro "Origin inesperado: $origem" ;;
esac
[[ -z "$(git status --porcelain)" ]] || erro "Ha alteracoes locais; use um clone limpo."
git fetch --quiet origin dev
[[ "$(git rev-parse HEAD)" == "$(git rev-parse refs/remotes/origin/dev)" ]] ||
  erro "Branch dev local desatualizada. Execute: git pull --ff-only"
arquivo="pocket-id-2.19.2.zip"
[[ -f "$arquivo" ]] || erro "ZIP nao encontrado: $arquivo"

temporario=$(mktemp -d) || erro "Nao foi possivel criar diretorio temporario."
trap 'rm -rf "$temporario"' EXIT

python3 - "$raiz/$arquivo" "$temporario" "$raiz" <<'PY'
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path

zip_path, stage, repo = map(Path, sys.argv[1:])
stage = stage.resolve()
repo = repo.resolve()
stub = (
    b"# Pocket ID\n\nRepository initialized. Application source code "
    b"will be added only after local security fixes and validation.\n"
)

with zipfile.ZipFile(zip_path) as archive:
    infos = archive.infolist()
    if len(infos) > 100000:
        raise SystemExit("ZIP excede o limite de entradas.")
    entries = []
    for info in infos:
        name = info.filename
        parts = name.rstrip("/").split("/")
        if any(not p or p in (".", "..", ".git") or ":" in p for p in parts):
            raise SystemExit(f"Caminho invalido no ZIP: {name!r}")
        if "\\" in name or "\x00" in name or name.startswith("/"):
            raise SystemExit(f"Caminho perigoso no ZIP: {name!r}")
        if not info.is_dir():
            entries.append((info, parts))
    if not entries:
        raise SystemExit("O ZIP nao contem arquivos.")
    total = sum(info.file_size for info, _ in entries)
    if total > 1024 * 1024 * 1024:
        raise SystemExit("ZIP excede o limite de 1 GiB descompactado.")
    roots = {parts[0] for _, parts in entries}
    strip_root = len(roots) == 1 and all(len(parts) > 1 for _, parts in entries)
    seen = set()
    regular = []
    links = []
    for info, parts in entries:
        rel = Path(*(parts[1:] if strip_root else parts))
        ident = rel.as_posix().casefold()
        if ident in seen:
            raise SystemExit(f"Caminho duplicado no ZIP: {rel}")
        seen.add(ident)
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFLNK):
            raise SystemExit(f"Tipo de entrada nao permitido: {rel}")
        (links if kind == stat.S_IFLNK else regular).append((info, rel, mode))

    for info, rel, mode in regular:
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("xb") as output:
            shutil.copyfileobj(source, output)
        target.chmod(0o755 if mode & 0o111 else 0o644)

    for info, rel, _ in links:
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        link = archive.read(info).decode("utf-8")
        if not link or os.path.isabs(link) or "\x00" in link:
            raise SystemExit(f"Link simbolico perigoso: {rel}")
        resolved = (target.parent / link).resolve()
        try:
            resolved.relative_to(stage)
        except ValueError:
            raise SystemExit(f"Link fora do projeto: {rel} -> {link}")
        target.symlink_to(link)

# Preflight antes de alterar os arquivos locais.
items = []
for source in stage.rglob("*"):
    if source.is_dir() and not source.is_symlink():
        continue
    rel = source.relative_to(stage)
    target = repo / rel
    for parent in target.parents:
        if parent == repo:
            break
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise SystemExit(f"Diretorio de destino invalido: {parent}")
    if target.exists() or target.is_symlink():
        if rel != Path("README.md") or not target.is_file() or target.read_bytes() != stub:
            raise SystemExit(f"Arquivo ja existente; sem sobrescrita: {rel}")
    items.append((source, target))

for source, target in items:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()  # Apenas README inicial conhecido, validado acima.
    shutil.move(str(source), str(target))
print(f"Extraidos {len(items)} arquivos na raiz do repositorio.")
PY

git rm -- "$arquivo"
git add -A
git diff --cached --quiet && erro "Nenhuma alteracao para publicar."
git commit -m "chore: extrair fontes Pocket ID 2.19.2 na dev"
git push origin HEAD:dev
printf '\nConcluido: arquivos publicados em dev; ZIP removido.\n'
