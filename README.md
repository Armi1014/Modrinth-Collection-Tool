````md
# Modrinth Collection Importer

Import a local mod list (for example exported from Prism Launcher) into a **Modrinth collection** with one command.

This tool:

- Reads a `modlist.json` containing your mods (names + URLs)
- Helps you resolve **non-Modrinth** entries (CurseForge, missing URLs) interactively
- Fetches your **Modrinth collections** via the official API
- Lets you pick which collection to update
- Updates that collection using the same API the Modrinth website uses
- Caches your collections locally so you don’t spam the API

If you maintain a client modpack and want a **clean, shareable Modrinth collection** for it, this is what you want.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Configuration (`config.json`)](#configuration-configjson)
  - [Getting a Modrinth Personal Access Token (PAT)](#getting-a-modrinth-personal-access-token-pat)
  - [Finding your `user_id`](#finding-your-user_id)
- [`modlist.json` (Input Mod List)](#modlistjson-input-mod-list)
- [Usage](#usage)
  - [Basic interactive run](#basic-interactive-run)
  - [Dry-run mode](#dry-run-mode)
  - [Custom paths](#custom-paths)
  - [Skipping the collection picker](#skipping-the-collection-picker)
- [Files Created](#files-created)
- [Notes & Limitations](#notes--limitations)

---

## Features

- Import an entire modpack from a single `modlist.json`
- Interactive handling of entries that don’t have a Modrinth URL
- Uses the official Modrinth API:
  - `/v3/user/.../collections`
  - `/v3/collection/...`
  - `/v2/project/...`
- Stores a snapshot of your collections in `modrinth_state.json`
- Has a **dry-run** mode (see exactly what would happen without changing anything)
- Secrets are not hard-coded; they live in `config.json` (which you should never commit)

---

## Project Structure

A typical repo layout:

```text
your-repo/
├─ main.py                 # the script
├─ config.json             # your Modrinth credentials (never commit this)
├─ modlist.json            # exported mod list from Prism Launcher (or similar)
└─ modrinth_state.json     # auto-generated snapshot of your collections
````

If your main script file is not called `main.py`, just adjust the commands below accordingly.

---

## Requirements

* Python **3.8+**
* [`requests`](https://pypi.org/project/requests/) library

Install dependencies:

```bash
pip install requests
```

---

## Configuration (`config.json`)

The script reads its settings from a `config.json` file in the same directory as `main.py`.

Example:

```json
{
  "token": "mrp_your_personal_access_token_here",
  "user_agent": "your-name/modrinth-collection-importer/0.1",
  "user_id": "UWlQXVVZ"
}
```

* `token`
  Your **Modrinth Personal Access Token (PAT)**. It must start with `mrp_...`.
* `user_agent`
  A custom identifier for this script. Modrinth expects non-generic User-Agents for API clients.
  Example: `"your-name/modrinth-collection-importer/0.1 (personal use)"`
* `user_id`
  Your Modrinth **user ID** (short ID, e.g. `"UWlQXVVZ"`).

### Security

Do not leak your token. At minimum, add these to `.gitignore`:

```gitignore
config.json
modrinth_state.json
```

Never commit real tokens or `config.json` to GitHub.

---

### Getting a Modrinth Personal Access Token (PAT)

1. Log in to Modrinth in your browser.
2. Go to your **Account / Settings** page.
3. Find **Personal Access Tokens**.
4. Create a new token:

   * Give it a sensible name, e.g. `Modpack Collection Importer`.
   * Give it scopes that allow **reading** and **modifying collections** for your user.
5. Copy the generated token (it should look like `mrp_XXXXXXXXXXXXXXXX`).
6. Put it into `config.json` as the value of `"token"`.

> Do **not** use the `authorization` value you see in your browser’s DevTools (those `mra_...` tokens).
> Those are session tokens and will break or get you 401s. Use a **PAT** (`mrp_...`) only.

---

### Finding your `user_id`

You only need to find this once.

#### Option A – From the API

If you’re comfortable with `curl`:

```bash
curl -H "Authorization: mrp_XXXXXXXXXXXXXXXX" \
     -H "User-Agent: your-name/modrinth-collection-importer/0.1" \
     https://api.modrinth.com/v3/user
```

In the JSON response, look for the `"id"` field.
That value is your `user_id`.

#### Option B – From browser DevTools

If you’ve seen a request like this in the Network tab:

```http
GET https://api.modrinth.com/v3/user/UWlQXVVZ/collections
```

Then `UWlQXVVZ` is your `user_id`. Put that in `config.json`.

---

## `modlist.json` (Input Mod List)

By default, the script expects a file named `modlist.json` in the same directory as `main.py`.

Format (simplified):

```json
[
  {
    "name": "3d-Skin-Layers",
    "url": "https://modrinth.com/mod/zV5r3pPn"
  },
  {
    "name": "Architectury",
    "url": "https://www.curseforge.com/projects/419699"
  },
  {
    "name": "No Mining Cooldown"
  }
]
```

* `name` – purely for display/debug. The script doesn’t depend on it.
* `url` – optional:

  * If it’s a **Modrinth mod URL** (e.g. `https://modrinth.com/mod/P7dR8mSH`), the script can resolve the project automatically.
  * If it is missing or points somewhere else (CurseForge, random link, etc.), the script will interactively ask what to do for that entry.

### Exporting from Prism Launcher

Prism Launcher can export your instance’s mod list.

Rough idea (exact labels depend on your version/theme):

1. Open **Prism Launcher**.
2. Right-click your modded instance → **Edit**.
3. Go to the **Mods** tab.
4. Look for something like **“Export mod list”**.
5. If it can export to JSON, use that and adapt the structure to match the example above if needed.

Save the final list as `modlist.json` next to `main.py`.

If you use another name or location, you can point the script to it with `--modlist`.

---

## Usage

All commands below assume the script file is called `main.py`.

### Basic interactive run

```bash
python main.py
```

What happens:

1. The script reads `config.json`.

2. It fetches your collections from Modrinth and writes a snapshot to `modrinth_state.json`.

3. It shows your collections and asks which one to use, for example:

   ```text
   Your collections:
     [1] Armi's Modrinth Collection  (id=tIDygMuC)
         A collection of mods curated by Armi for Minecraft.

   Select collection by number (or paste collection ID, or 'q' to quit) >
   ```

4. It loads `modlist.json` and walks through each entry:

   * If `url` is a Modrinth URL → resolves it automatically.
   * If `url` is missing or non-Modrinth → you see a prompt like:

     ```text
     Entry needs attention: Architectury
       Current URL: https://www.curseforge.com/projects/419699
       [u] enter Modrinth URL  |  [s] skip this mod  |  [q] abort >
     ```

5. After processing the list, it prints a summary, for example:

   ```text
   [summary] To add: 81 new project(s). Skipped: 0. Final collection size will be 83.
   Proceed with updating the collection? [y/N] >
   ```

6. If you confirm with `y`, it sends a single `PATCH` request like:

   ```http
   PATCH /v3/collection/tIDygMuC
   Body: {"new_projects": ["P7dR8mSH","AANobbMI", ...]}
   ```

   and updates the collection on Modrinth.

---

### Dry-run mode

To see what would happen without actually patching the collection:

```bash
python main.py --dry-run
```

* The script still reads the config and modlist.
* It still resolves project IDs and prints a summary.
* It **does not** send the final `PATCH` request.

Useful if you don’t trust your `modlist.json` yet.

---

### Custom paths

Use a different config file:

```bash
python main.py --config my_config.json
```

Use a different modlist file:

```bash
python main.py --modlist my_modlist.json
```

Combine them:

```bash
python main.py --config my_config.json --modlist instances/fabric-pack/modlist.json
```

---

### Skipping the collection picker

If you already know the collection ID (for example `tIDygMuC`):

```bash
python main.py --collection-id tIDygMuC
```

The script will:

* Sync collections and update `modrinth_state.json`
* Validate that `tIDygMuC` belongs to your user
* Use it directly without the interactive selection

You can combine this with all other flags (`--dry-run`, `--config`, `--modlist`).

---

## Files Created

* `modrinth_state.json`
  Local snapshot of your collections (`user_id`, collection list, and a timestamp).
  You can delete it any time; the script will just recreate it.

* Your own `config.json`
  Contains your token and `user_id`. **Do not commit this.**

---

## Notes & Limitations

* Only mods that exist on **Modrinth** can be added.
  If some mods are CurseForge-only or custom, you will have to:

  * Find a Modrinth equivalent, or
  * Skip them when prompted.
* The script uses the public Modrinth API and is subject to normal **rate limits**.
  For a typical modpack (tens of mods), this is not a problem.
* If Modrinth changes their API for collections in the future, this script may need updates.

If you extend it (non-interactive modes, auto-creating collections, other launcher formats), keep your tokens out of version control and don’t push anything that contains real secrets.

```
::contentReference[oaicite:0]{index=0}
```
