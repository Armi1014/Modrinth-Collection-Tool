#!/usr/bin/env python3
"""
modrinth_import_modlist.py

- Reads a modlist.json like:
  [
      {"name": "Fabric API", "url": "https://modrinth.com/mod/P7dR8mSH"},
      ...
  ]

- Asks you what to do with entries that don't have a valid Modrinth URL
  (curseforge links, missing urls, etc).

- Fetches your Modrinth collections using your user_id and token.

- Lets you pick a collection (or supply one via --collection-id).

- Adds the listed mods to that collection by PATCHing /v3/collection/<id>.

- Also writes a local "modrinth_state.json" with:
    {
      "user_id": "...",
      "collections": [...],  # raw API response
      "synced_at": "2025-11-07T15:24:09.123456+00:00"
    }
  so you have a snapshot of all your collections on disk.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

API_BASE = "https://api.modrinth.com/v3"
DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_MODLIST_PATH = "modlist.json"
STATE_PATH = Path("modrinth_state.json")


class ConfigError(RuntimeError):
    pass


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"Config file not found: {p.resolve()}")

    with p.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    missing = [k for k in ("token", "user_agent", "user_id") if k not in cfg or not cfg[k]]
    if missing:
        raise ConfigError(
            "config.json is missing required field(s): "
            + ", ".join(missing)
            + "\nExpected at least:\n"
            + '{ "token": "mrp_...", "user_agent": "your-name/your-tool", "user_id": "UWlQXVVZ" }'
        )

    return cfg


def base_headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    return {
        "Authorization": cfg["token"],
        "User-Agent": cfg["user_agent"],
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def load_modlist(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Modlist file not found: {p.resolve()}")

    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("modlist.json must be a JSON array of objects")

    return data


def extract_modrinth_project_id(url: str) -> Optional[str]:
    """
    Accepts URLs like:
      https://modrinth.com/mod/zV5r3pPn
      https://modrinth.com/mod/zV5r3pPn/version/1.0.0
    Returns the project slug/ID (zV5r3pPn) or None if the URL isn't a Modrinth mod URL.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = parsed.netloc.lower()
    if host not in {"modrinth.com", "www.modrinth.com"}:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "mod":
        return parts[1]

    return None


def prompt_for_modrinth_url(entry: Dict[str, Any]) -> Optional[str]:
    """
    Ask the user what to do when we don't have a usable Modrinth URL.
    Returns a Modrinth project ID (slug) or None (skip).
    """
    name = entry.get("name", "<no name>")
    old_url = entry.get("url")

    print()
    print(f"Entry needs attention: {name}")
    if old_url:
        print(f"  Current URL: {old_url}")
    else:
        print("  Current URL: <missing>")

    while True:
        ans = input("  [u] enter Modrinth URL  |  [s] skip this mod  |  [q] abort > ").strip().lower()
        if ans in {"q", "quit"}:
            print("Aborting by user request.")
            sys.exit(1)
        if ans in {"s", "skip"}:
            print("  -> Skipping this mod.")
            return None
        if ans in {"u", "url"}:
            new_url = input("  Paste Modrinth URL (https://modrinth.com/mod/...) > ").strip()
            pid = extract_modrinth_project_id(new_url)
            if not pid:
                print("  That doesn't look like a valid Modrinth mod URL. Try again.")
                continue
            print(f"  -> Using project ID: {pid}")
            return pid


def collect_project_ids_from_modlist(modlist: List[Dict[str, Any]]) -> Tuple[List[str], int]:
    """
    Walk through modlist entries and produce a list of Modrinth project IDs.
    Returns (project_ids, skipped_count).
    """
    project_ids: List[str] = []
    skipped = 0

    for entry in modlist:
        url = entry.get("url")
        pid: Optional[str] = None

        if url:
            pid = extract_modrinth_project_id(url)

        if not pid:
            # Not a valid Modrinth URL -> ask the user
            pid = prompt_for_modrinth_url(entry)

        if pid:
            if pid not in project_ids:
                project_ids.append(pid)
        else:
            skipped += 1

    return project_ids, skipped


def fetch_collections(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    GET /v3/user/{user_id}/collections
    """
    url = f"{API_BASE}/user/{cfg['user_id']}/collections"
    resp = requests.get(url, headers=base_headers(cfg))
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch collections (status {resp.status_code}): {resp.text}"
        )
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected response format when fetching collections")
    return data


def load_state() -> Dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # If it's corrupted, just ignore it; we'll overwrite.
        return {}


def save_state(state: Dict[str, Any]) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.replace(STATE_PATH)


def sync_collections_to_state(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fetch collections from the API and store them in modrinth_state.json.
    Returns the fresh list of collections.
    """
    collections = fetch_collections(cfg)
    state = load_state()
    state["user_id"] = cfg["user_id"]
    state["collections"] = collections
    state["synced_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(
        f"[info] Synced {len(collections)} collection(s) into {STATE_PATH.name} "
        f"(user_id={cfg['user_id']})."
    )
    return collections


def choose_collection(collections: List[Dict[str, Any]], explicit_id: Optional[str]) -> str:
    """
    Let the user choose a collection ID.
    If explicit_id is provided, validate it and use that.
    """
    if explicit_id:
        for col in collections:
            if col.get("id") == explicit_id:
                print(f"[info] Using collection {col.get('name')!r} ({explicit_id}) from --collection-id")
                return explicit_id
        raise RuntimeError(
            f"Collection ID {explicit_id} not found in your collections. "
            f"Did you use the right account / user_id?"
        )

    if not collections:
        print("You don't have any collections yet.")
        print("Create one in the Modrinth UI, then run this script again.")
        sys.exit(1)

    print("\nYour collections:")
    for idx, col in enumerate(collections, start=1):
        cid = col.get("id")
        name = col.get("name") or "<no name>"
        desc = col.get("description") or ""
        print(f"  [{idx}] {name}  (id={cid})")
        if desc:
            print(f"      {desc}")

    while True:
        ans = input("Select collection by number (or paste collection ID, or 'q' to quit) > ").strip()
        if ans.lower() in {"q", "quit"}:
            print("Aborting by user request.")
            sys.exit(1)

        # If they pasted an ID directly:
        for col in collections:
            if ans == col.get("id"):
                print(f"[info] Using collection {col.get('name')!r} ({ans})")
                return ans

        # Otherwise, try numeric choice
        try:
            idx = int(ans)
        except ValueError:
            print("Please enter a valid number or a collection ID.")
            continue

        if 1 <= idx <= len(collections):
            col = collections[idx - 1]
            print(f"[info] Using collection {col.get('name')!r} ({col.get('id')})")
            return col.get("id")  # type: ignore[return-value]

        print(f"Please enter a number between 1 and {len(collections)}.")


def fetch_collection_details(cfg: Dict[str, Any], collection_id: str) -> Dict[str, Any]:
    url = f"{API_BASE}/collection/{collection_id}"
    resp = requests.get(url, headers=base_headers(cfg))
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch collection {collection_id} (status {resp.status_code}): {resp.text}"
        )
    return resp.json()


def patch_collection_projects(
    cfg: Dict[str, Any],
    collection_id: str,
    project_ids: List[str],
    dry_run: bool = False,
) -> None:
    """
    PATCH /v3/collection/{id} with the full list of project IDs.
    Uses the same 'new_projects' payload the Modrinth frontend uses.
    """
    payload = {"new_projects": project_ids}
    print(f"[info] PATCH payload for collection {collection_id}: {json.dumps(payload)}")

    if dry_run:
        print("[dry-run] Skipping PATCH request.")
        return

    url = f"{API_BASE}/collection/{collection_id}"
    resp = requests.patch(url, headers=base_headers(cfg), data=json.dumps(payload))
    if resp.status_code != 204:
        raise RuntimeError(
            f"Collection update failed: {resp.status_code} {resp.text}\n"
            "If you see 401 'unauthorized', double-check that you're using a "
            "personal access token (PAT) starting with 'mrp_' and that it has "
            "the scopes required for collections."
        )
    print("[ok] Collection updated successfully.")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Import a modlist.json into a Modrinth collection."
    )
    parser.add_argument(
        "-c", "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to config JSON (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "-m", "--modlist",
        default=DEFAULT_MODLIST_PATH,
        help=f"Path to modlist JSON (default: {DEFAULT_MODLIST_PATH})",
    )
    parser.add_argument(
        "--collection-id",
        help="Collection ID to use (skips the interactive collection picker).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do everything except the final PATCH call.",
    )

    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    # Sync collections and store them locally
    try:
        collections = sync_collections_to_state(cfg)
    except Exception as e:
        print(f"[warn] Failed to sync collections from API: {e}")
        state = load_state()
        collections = state.get("collections") or []
        if not collections:
            print("No collections in local state either; cannot continue.")
            sys.exit(1)
        else:
            print(
                f"[info] Falling back to collections from {STATE_PATH.name} "
                f"(snapshot may be outdated)."
            )

    collection_id = choose_collection(collections, args.collection_id)

    # Load modlist and compute project IDs
    try:
        modlist = load_modlist(args.modlist)
    except Exception as e:
        print(f"Failed to load modlist: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[info] Loaded {len(modlist)} entries from {args.modlist}")

    project_ids_from_modlist, skipped = collect_project_ids_from_modlist(modlist)

    print(f"[info] Collected {len(project_ids_from_modlist)} unique Modrinth project(s) from modlist.")
    if skipped:
        print(f"[info] Skipped {skipped} mod(s) (no Modrinth URL and you chose to skip).")

    # Fetch current collection details to merge with existing projects
    coll = fetch_collection_details(cfg, collection_id)
    existing_projects = coll.get("projects") or []
    if not isinstance(existing_projects, list):
        print("[warn] Unexpected 'projects' field format in collection; treating as empty.")
        existing_projects = []

    existing_set = set(str(p) for p in existing_projects)
    to_add_set = set(project_ids_from_modlist)

    final_set = sorted(existing_set.union(to_add_set))

    added_count = len(final_set) - len(existing_set)
    print()
    print(
        f"[summary] To add: {added_count} new project(s). Skipped: {skipped}. "
        f"Final collection size will be {len(final_set)}."
    )

    confirm = input("Proceed with updating the collection? [y/N] > ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("Aborted by user.")
        sys.exit(0)

    print(f"[info] Patching collection {collection_id} with {len(final_set)} total project(s)...")
    patch_collection_projects(cfg, collection_id, list(final_set), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
