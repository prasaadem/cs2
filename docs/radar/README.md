# Radar images for the heatmaps

For each map, put two files from the game in this folder:

- `<map>.png`: the overhead radar image, for example `de_mirage.png`
- `<map>.txt`: the map's overview file, which holds `pos_x`, `pos_y` and `scale`

Then run `python stats/build_site.py`. It writes `overviews.json`, and the heatmap draws the map underneath the data. Maps without these files keep the traced layout.

## Where to get them (from your own CS2 install)

Open `game/csgo/pak01_dir.vpk` in [Source 2 Viewer](https://valveresourceformat.github.io/), then:

- **Image:** `panorama/images/overheadmaps/<map>_radar_psd.vtex_c`. Export it as PNG and rename it to `<map>.png`.
- **Overview:** `resource/overviews/<map>.txt`. Export it as is.

Workshop maps (Seaside, Foroglio, Guard and so on) keep the same two files inside their own `.vpk` in the Steam workshop folder (`steamapps/workshop/content/730/<id>/`).
