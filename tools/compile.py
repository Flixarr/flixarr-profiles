#!/usr/bin/env python3
"""Build profiles.json from recipes.json and a checkout of the TRaSH Guides repo.

  python3 tools/compile.py /path/to/TRaSH-Guides/Guides

For each recipe and app (Radarr, Sonarr) it takes the TRaSH quality profile named as `base`, adds the
custom formats TRaSH recommends for it (the profile's own list, plus every format group that is on by
default for that profile), then applies the recipe: the ladder of qualities, the cutoff, the score rules
and the upgrade rules.

A "prefer" profile only ranks: the formats TRaSH rejects become small penalties, apart from the short
`hard` list in recipes.json, which stays blocked. A "strict" profile keeps every TRaSH block.

The output uses Radarr/Sonarr's own shapes, keyed by name instead of database IDs (those differ per
install): custom formats as they're posted to /api/v3/customformat, and the quality profile as it's
posted to /api/v3/qualityprofile with qualities and formats referenced by name. Flixarr resolves the
names to IDs on each server when it adds or updates the profile, and swaps "$library" for the language
the owner chose.
"""
import hashlib, json, subprocess, sys, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCK = -100000  # far below anything the positive scores can add up to
REJECTED = -10000  # what TRaSH scores a format it rejects


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


def item(name, qualities):
    """One ladder entry: a plain quality, or a group whose qualities count as equal."""
    if len(qualities) == 1:
        return {"name": qualities[0], "allowed": True}
    return {"name": name, "allowed": True, "items": qualities}


def remux(app, res):
    return f"Remux-{res}" if app == "radarr" else f"Bluray-{res} Remux"


def web(res):
    return [f"WEBRip-{res}", f"WEBDL-{res}"]


def other(app, res):
    """The sources only used when nothing better exists at a resolution."""
    return [f"HDTV-{res}"] + ([remux(app, res)] if res != "720p" else [])


def sd(app):
    return ["Bluray-576p", "Bluray-480p", "WEBRip-480p", "WEBDL-480p", "DVD"] + (["DVD-R"] if app == "radarr" else []) + ["SDTV"]


def step(app, res, style):
    """A resolution on the ladder. Below-cutoff sources share one group so they never upgrade into each other."""
    if res == "SD":
        return [item("SD", sd(app))]
    if res in ("remux-2160p", "remux-1080p"):
        return [{"name": remux(app, res.split("-")[1]), "allowed": True}]
    if res in ("web-2160p", "web-1080p"):
        r = res.split("-")[1]
        return [item(f"WEB {r}", web(r))]
    if style == "merged":  # the score decides between sources, so a small copy can beat a bigger one
        return [item(res, [f"Bluray-{res}"] + web(res) + other(app, res))]
    return [{"name": f"Bluray-{res}", "allowed": True}, item(f"WEB {res}", web(res)), item(f"Other {res}", other(app, res))]


def build(app, guides, recipe, rules, extra):
    j = guides / "docs" / "json" / app
    base = load(j / "quality-profiles" / f"{recipe['base']}.json")
    cfs = {}
    for f in (j / "cf").glob("*.json"):
        cf = load(f)
        cfs[cf["trash_id"]] = cf
    by_name = {cf["name"]: cf for cf in cfs.values()}
    score_set = base.get("trash_score_set", "default")
    mode = recipe["mode"]
    overrides = recipe.get("scores", {})

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
    # The hard blocks apply to every profile, even when TRaSH leaves one out of a base.
    wanted += [by_name[n]["trash_id"] for n in rules["hard"] if n in by_name]

    seen, formats, items = set(), [], []
    for tid in wanted:
        if tid in seen or tid not in cfs:
            continue
        seen.add(tid)
        cf = cfs[tid]
        name = cf["name"]
        if name in rules["replaced"]:  # the language rule below takes over
            continue
        trash = cf.get("trash_scores", {})
        score = trash.get(score_set, trash.get("default", 0))
        if name in rules["hard"]:
            score = BLOCK
        elif mode == "strict":
            score = BLOCK if score <= REJECTED else score
        else:
            if name in rules["no_penalty"]:
                continue  # allowed, and neither helped nor hurt
            if score <= REJECTED:
                score = rules["soft"]
        score = overrides.get(name, score)
        formats.append(native_cf(cf))
        items.append({"name": name, "score": score})
    have = {i["name"] for i in items}
    for name, score in overrides.items():
        if name in extra and name not in have:
            formats.append(extra[name])
            items.append({"name": name, "score": score})
    lang = recipe["language"]
    for name, score in ((rules["language"]["library"], lang["library"]), (rules["language"]["both"], lang["both"]), (rules["language"]["other"], BLOCK)):
        formats.append(extra[name])
        items.append({"name": name, "score": score})

    # Qualities, best first. Anything the ladder doesn't name stays off.
    if "ladder" in recipe:
        q = [i for res in recipe["ladder"] for i in step(app, res, recipe.get("style"))]
    else:
        q = [dict(i) for i in base["items"]]
        if recipe.get("append"):
            names = [x for res in recipe["append"] for i in step(app, res, "merged") for x in i.get("items", [i["name"]])]
            q = [i for i in q if i["name"] not in names] + [i for res in recipe["append"] for i in step(app, res, "merged")]
    profile = {"upgradeAllowed": True, "cutoff": recipe.get("cutoff", base["cutoff"]),
               "minFormatScore": recipe["floor"], "cutoffFormatScore": recipe["stop"],
               "minUpgradeFormatScore": rules["upgrade"], "items": q, "formatItems": items}
    if app == "radarr":
        profile["language"] = "Any"  # the language formats decide what's right
    if not any(i["name"] == profile["cutoff"] and i.get("allowed") for i in q):
        sys.exit(f"{app} {recipe['base']}: cutoff {profile['cutoff']} isn't an allowed quality")
    return {"basedOn": {"name": base["name"], "trashId": base["trash_id"], "url": base.get("trash_url", "")}, "profile": profile}, formats


def spec(name, impl, value, negate=False, required=False):
    return {"name": name, "implementation": impl, "negate": negate, "required": required, "fields": [{"name": "value", "value": value}]}


def extra_formats(app, recipes):
    """The formats Flixarr adds to TRaSH's: the language rule, small-file groups and remuxes."""
    names = recipes["rules"]["language"]
    lib, orig = "$library", -2
    fmt = lambda n, specs: (n, {"name": n, "includeCustomFormatWhenRenaming": False, "specifications": specs})
    remux_spec = spec("Remux", "QualityModifierSpecification", 5, required=True) if app == "radarr" else spec("Remux", "SourceSpecification", 7, required=True)
    groups = [spec(g["name"], "ReleaseTitleSpecification", g["match"]) for g in recipes["smallFileGroups"][app]]
    return dict([
        fmt(names["library"], [spec("Library language", "LanguageSpecification", lib, required=True)]),
        fmt(names["both"], [spec("Library language", "LanguageSpecification", lib, required=True), spec("Original language", "LanguageSpecification", orig, required=True)]),
        fmt(names["other"], [spec("Not the library language", "LanguageSpecification", lib, negate=True, required=True), spec("Not the original language", "LanguageSpecification", orig, negate=True, required=True)]),
        fmt("Small File Groups", groups),
        fmt("Remux", [remux_spec]),
    ])


def sizes(app, guides, recipes):
    """Radarr/Sonarr's Quality Definitions: low minimums that only stop fake files, TRaSH's preferred and maximum."""
    rule = recipes["sizes"]
    trash = {q["quality"]: q for q in load(guides / "docs" / "json" / app / "quality-size" / ("movie.json" if app == "radarr" else "series.json"))["qualities"]}
    out = {}
    for res in ("720p", "1080p", "2160p"):
        names = [f"Bluray-{res}"] + web(res) + [f"HDTV-{res}"]
        for n in names:
            out[n] = {"min": rule["min"][res], "preferred": trash[n]["preferred"], "max": trash[n]["max"]}
    for res in ("1080p", "2160p"):
        n = remux(app, res)
        out[n] = {"min": rule["remux"][res], "preferred": trash[n]["preferred"], "max": trash[n]["max"]}
    for n in sd(app):
        out[n] = {"min": rule["min"]["SD"]}
    return out


def main():
    guides = pathlib.Path(sys.argv[1])
    commit = subprocess.run(["git", "-C", str(guides), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    recipes = load(ROOT / "recipes.json")
    extra = {a: extra_formats(a, recipes) for a in ("radarr", "sonarr")}
    out, library = [], {"radarr": {}, "sonarr": {}}
    for r in recipes["profiles"]:
        p = {k: r[k] for k in ("id", "name", "label", "description", "defaultOn")}
        used = {}
        for app in ("radarr", "sonarr"):
            if app in r:
                p[app], formats = build(app, guides, r[app], recipes["rules"], extra[app])
                for f in formats:
                    library[app][f["name"]] = f
                used[app] = [library[app][i["name"]] for i in p[app]["profile"]["formatItems"]]
        # rev changes whenever anything Flixarr would push for this profile changes (including the
        # custom formats it uses), so installs know to sync.
        body = json.dumps({"profile": {a: p.get(a) for a in ("radarr", "sonarr")}, "formats": used}, sort_keys=True).encode()
        p["rev"] = hashlib.sha256(body).hexdigest()[:12]
        out.append(p)
    limits = {a: sizes(a, guides, recipes) for a in ("radarr", "sonarr")}
    prev = load(ROOT / "profiles.json") if (ROOT / "profiles.json").exists() else {}
    changed = [p["id"] for p in out if p["rev"] not in {x["rev"] for x in prev.get("profiles", [])}]
    doc = {"schema": 1, "version": datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M") if changed or not prev or prev.get("sizes") != limits else prev["version"],
           "source": {"name": "TRaSH Guides", "url": "https://trash-guides.info", "commit": commit, "license": "MIT"}, "profiles": out,
           # Every custom format any profile uses, once per app, keyed by name (profiles list them in formatItems).
           "customFormats": {a: dict(sorted(library[a].items())) for a in library},
           "sizes": limits}
    (ROOT / "profiles.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"profiles.json: version {doc['version']}, {len(out)} profiles, changed: {changed or 'none'}")
    for p in out:
        for app in ("radarr", "sonarr"):
            if app in p:
                print(f"  {p['id']:14} {app}: {len(p[app]['profile']['formatItems'])} formats, cutoff {p[app]['profile']['cutoff']}")
    print(f"  library: {len(doc['customFormats']['radarr'])} radarr + {len(doc['customFormats']['sonarr'])} sonarr formats")


if __name__ == "__main__":
    main()
