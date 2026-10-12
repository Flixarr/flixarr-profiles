# Flixarr quality profiles

The quality profiles every Flixarr install can add to its Radarr and Sonarr. Flixarr downloads `profiles.json` (through `api.flixarr.app`), creates the custom formats and quality profiles in each connected server as **Flixarr · Standard**, **Flixarr · Space Saver** and **Flixarr · 4K**, and keeps them up to date when this file changes. If you edit one of them in Radarr or Sonarr, your version is kept and Flixarr offers the update instead of overwriting it.

| Profile | Radarr | Sonarr |
|---|---|---|
| **Standard (1080p)** | 1080p Bluray + WEB | 1080p WEB |
| **Space Saver (720p)** | 720p Bluray + WEB | 720p WEB |
| **4K** | 2160p Bluray + WEB, HDR and Dolby Vision preferred | 2160p WEB, HDR and Dolby Vision preferred |

HD profiles block x265, BR-DISK, LQ groups, 3D and other unwanted releases.

## How it's built

`recipes.json` is the source: each profile starts from a [TRaSH Guides](https://trash-guides.info) profile and lists only what Flixarr changes. `tools/compile.py` turns the recipes into `profiles.json`:

```
git clone --depth 1 https://github.com/TRaSH-Guides/Guides.git /tmp/trash
python3 tools/compile.py /tmp/trash
```

Each profile in `profiles.json` gets a `rev` that changes whenever anything Flixarr would push for it changes, and the file's `version` changes when any profile does. Flixarr installs use these to know when to sync.

## Credits

Custom formats, scores and the base profiles come from the [TRaSH Guides](https://github.com/TRaSH-Guides/Guides) (MIT). Thank you to the TRaSH team.
