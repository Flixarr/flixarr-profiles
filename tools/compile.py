#!/usr/bin/env python3
"""Build profiles.json from recipes.json and a checkout of the TRaSH Guides repo.

  python3 tools/compile.py /path/to/TRaSH-Guides/Guides

For each recipe and app (Radarr, Sonarr) it takes the TRaSH quality profile named as `base`, adds the
custom formats TRaSH recommends for it (the profile's own list, plus every format group that is on by
default for that profile), and applies the recipe's changes (`allowed` qualities, `cutoff`).

The output uses Radarr/Sonarr's own shapes, keyed by name instead of database IDs (those differ per
install): custom formats as they're posted to /api/v3/customformat, and the quality profile as it's
posted to /api/v3/qualityprofile with qualities and formats referenced by name. Flixarr resolves the
names to IDs on each server when it adds or updates the profile.
"""
import hashlib, json, subprocess, sys, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(p):
    return json.loads(pathlib.Path(p).read_text())


def native_cf(cf):
    """TRaSH custom format → Radarr/Sonarr customformat body (fields become name/value pairs)."""
    specs = []
    for s in cf["specifications"]:
        fields = s.get("fields", {})
        if isinstance(fields, dict):
            fields = [{"name": k, "value": v} for k, v in fields.items()]
        specs.append({"name": s["name"], "implementation": s["implementation"], "negate": s.get("negate", False),
                      "required": s.get("required", False), "fields": fields})
    return {"name": cf["name"], "includeCustomFormatWhenRenaming": cf.get("includeCustomFormatWhenRenaming", False), "specifications": specs}


def build(app, guides, recipe):
    j = guides / "docs" / "json" / app
    base = load(j / "quality-profiles" / f"{recipe['base']}.json")
    cfs = {}
    for f in (j / "cf").glob("*.json"):
        cf = load(f)
        cfs[cf["trash_id"]] = cf
    score_set = base.get("trash_score_set", "default")

    # Formats: the profile's own list, then the groups TRaSH turns on by default for this profile.
    wanted = list(base["formatItems"].values())
    for g in sorted((j / "cf-groups").glob("*.json")):
        grp = load(g)
        if str(grp.get("default")).lower() != "true":
            continue
        if base["trash_id"] not in grp.get("quality_profiles", {}).get("include", {}).values():
            continue
        for c in grp["custom_formats"]:
            if c.get("required") or c.get("default"):
                wanted.append(c["trash_id"])
    seen, formats, items = set(), [], []
    for tid in wanted:
        if tid in seen or tid not in cfs:
            continue
        seen.add(tid)
        cf = cfs[tid]
        scores = cf.get("trash_scores", {})
        formats.append(native_cf(cf))
        items.append({"name": cf["name"], "score": scores.get(score_set, scores.get("default", 0))})

    # Qualities, best first. `allowed` (if given) lists the only qualities to grab, in order of preference.
    q = [dict(i) for i in base["items"]]
    if "allowed" in recipe:
        order = recipe["allowed"]
        byname = {i["name"]: i for i in q}
        missing = [n for n in order if n not in byname]
        if missing:
            sys.exit(f"{app} {recipe['base']}: no quality named {missing}")
        q = [dict(byname[n], allowed=True) for n in order] + [dict(i, allowed=False) for i in q if i["name"] not in order]
    profile = {"upgradeAllowed": base.get("upgradeAllowed", True), "cutoff": recipe.get("cutoff", base["cutoff"]),
               "minFormatScore": base.get("minFormatScore", 0), "cutoffFormatScore": base.get("cutoffFormatScore", 10000),
               "minUpgradeFormatScore": base.get("minUpgradeFormatScore", 1), "items": q, "formatItems": items}
    if base.get("language"):
        profile["language"] = base["language"]
    if not any(i["name"] == profile["cutoff"] and i.get("allowed") for i in q):
        sys.exit(f"{app} {recipe['base']}: cutoff {profile['cutoff']} isn't an allowed quality")
    return {"basedOn": {"name": base["name"], "trashId": base["trash_id"], "url": base.get("trash_url", "")}, "profile": profile}, formats


def main():
    guides = pathlib.Path(sys.argv[1])
    commit = subprocess.run(["git", "-C", str(guides), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    recipes = load(ROOT / "recipes.json")
    out, library = [], {"radarr": {}, "sonarr": {}}
    for r in recipes["profiles"]:
        p = {k: r[k] for k in ("id", "name", "label", "description")}
        used = {}
        for app in ("radarr", "sonarr"):
            if app in r:
                p[app], formats = build(app, guides, r[app])
                for f in formats:
                    library[app][f["name"]] = f
                used[app] = [library[app][i["name"]] for i in p[app]["profile"]["formatItems"]]
        # rev changes whenever anything Flixarr would push for this profile changes (including the
        # custom formats it uses), so installs know to sync.
        body = json.dumps({"profile": {a: p.get(a) for a in ("radarr", "sonarr")}, "formats": used}, sort_keys=True).encode()
        p["rev"] = hashlib.sha256(body).hexdigest()[:12]
        out.append(p)
    prev = load(ROOT / "profiles.json") if (ROOT / "profiles.json").exists() else {}
    changed = [p["id"] for p in out if p["rev"] not in {x["rev"] for x in prev.get("profiles", [])}]
    doc = {"schema": 1, "version": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M") if changed or not prev else prev["version"],
           "source": {"name": "TRaSH Guides", "url": "https://trash-guides.info", "commit": commit, "license": "MIT"}, "profiles": out,
           # Every custom format any profile uses, once per app, keyed by name (profiles list them in formatItems).
           "customFormats": {a: dict(sorted(library[a].items())) for a in library}}
    (ROOT / "profiles.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"profiles.json: version {doc['version']}, {len(out)} profiles, changed: {changed or 'none'}")
    for p in out:
        for app in ("radarr", "sonarr"):
            if app in p:
                print(f"  {p['id']:12} {app}: {len(p[app]['profile']['formatItems'])} formats, cutoff {p[app]['profile']['cutoff']}")
    print(f"  library: {len(doc['customFormats']['radarr'])} radarr + {len(doc['customFormats']['sonarr'])} sonarr formats")


if __name__ == "__main__":
    main()
