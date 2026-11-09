# Flixarr quality profiles

The quality profiles every Flixarr install can add to its Radarr and Sonarr. Flixarr downloads `profiles.json` (through `api.flixarr.app`), creates the custom formats and quality profiles in each connected server as **Flixarr · Standard**, **Flixarr · Space Saver** and **Flixarr · 4K**, and keeps them up to date when this file changes. If you edit one of them in Radarr or Sonarr, your version is kept and Flixarr offers the update instead of overwriting it.

| Profile | Starts on | Tries, in order | What it aims for |
|---|---|---|---|
| **Space Saver** | Yes | 720p, 1080p, 4K, SD | Small files first |
| **Standard** | Yes | 1080p, 720p, 4K, SD | A good 1080p copy |
| **High Quality** | Yes | 4K, 1080p, 720p, SD | A great 4K copy with HDR and top audio |
| **No Compromise** | No | 4K remux, 1080p remux, 4K WEB, 1080p WEB | Disc quality, strict |
| **Anime** | No | TRaSH's anime order, then 4K | Dual audio and the anime groups fans prefer |

All but No Compromise are prefer profiles: if a usable copy exists, it downloads, and a better one replaces it later. They only block wrong languages, theater copies, disc images, extras, 3D, line or mic dubbed audio and upscaled copies. An upgrade needs a score jump of at least 500.

## How it's built

`recipes.json` is the source: each profile starts from a [TRaSH Guides](https://trash-guides.info) profile and lists only what Flixarr changes. `tools/compile.py` turns the recipes into `profiles.json`:

```
git clone --depth 1 https://github.com/TRaSH-Guides/Guides.git /tmp/trash
python3 tools/compile.py /tmp/trash
```

Each profile in `profiles.json` gets a `rev` that changes whenever anything Flixarr would push for it changes, and the file's `version` changes when any profile does. Flixarr installs use these to know when to sync.

## Credits

Custom formats, scores and the base profiles come from the [TRaSH Guides](https://github.com/TRaSH-Guides/Guides) (MIT). Thank you to the TRaSH team.
