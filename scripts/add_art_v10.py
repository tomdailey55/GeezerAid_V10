#!/usr/bin/env python3
"""Add NEW impressionist paintings to the Genius TV V10 rotation.

Downloads public-domain images from Wikimedia Commons and prints the JS array
entries to append to gtv_chrome/js/gtv.js (ART + ART_TITLES, same order).

Usage:
    python3 add_art_v10.py --dry-run     # verify every URL resolves first
    python3 add_art_v10.py               # download to ~/genius-tv/art
"""
import argparse, json, sys, time, urllib.parse, urllib.request
from pathlib import Path

UA = "GeniusTV-ArtFetcher/1.0 (personal home display; contact: geezeraid@gmail.com)"
WIDTH = 3840
DELAY = 1.5

# (local_name, "Artist — Title", "Commons File:name")
# NEW impressionist / post-impressionist works, heavy on the impressionists.
# None of these collide with the 94 already on disk.
ART = [
    # ── Monet (12) ────────────────────────────────────────────────────────
    ("monet_waterlilies_1907",   "Monet — Water Lilies (1907)",          "Claude Monet - Water Lilies, 1907.jpg"),
    ("monet_japanese_bridge",    "Monet — The Japanese Bridge",          "Claude Monet - The Japanese Bridge - Google Art Project.jpg"),
    ("monet_london_parliament",  "Monet — Houses of Parliament, London", "Claude Monet - Houses of Parliament, London - Google Art Project.jpg"),
    ("monet_veheuil",            "Monet — Vétheuil in Summer",           "Claude Monet - Vétheuil in Summer - Google Art Project.jpg"),
    ("monet_poppy_field",        "Monet — Poppy Field near Argenteuil",  "Claude Monet - Poppy Field near Argenteuil - Google Art Project.jpg"),
    ("monet_haystacks_morning",  "Monet — Haystacks (Morning)",          "Claude Monet - Haystacks (Morning Effect) - Google Art Project.jpg"),
    ("monet_waterlily_pond",     "Monet — The Water-Lily Pond",          "Claude Monet - The Water-Lily Pond - Google Art Project.jpg"),
    ("monet_argenteuil",         "Monet — Argenteuil",                   "Claude Monet - Argenteuil - Google Art Project.jpg"),
    ("monet_giverny_morning",    "Monet — Morning at Giverny",           "Claude Monet - Morning at Giverny - Google Art Project.jpg"),
    ("monet_tulips_holland",     "Monet — Tulips in Holland",            "Claude Monet - Tulips in Holland - Google Art Project.jpg"),
    ("monet_boats_argenteuil",   "Monet — Boats at Argenteuil",          "Claude Monet - Boats at Argenteuil - Google Art Project.jpg"),
    ("monet_waterlilies_clouds", "Monet — Water Lilies and Clouds",      "Claude Monet - Water Lilies and Clouds - Google Art Project.jpg"),

    # ── Renoir (6) ────────────────────────────────────────────────────────
    ("renoir_dance_bougival",    "Renoir — Dance at Bougival",           "Pierre-Auguste Renoir - Dance at Bougival - Google Art Project.jpg"),
    ("renoir_dance_city",        "Renoir — Dance in the City",           "Pierre-Auguste Renoir - Dance in the City - Google Art Project.jpg"),
    ("renoir_dance_country",     "Renoir — Dance in the Country",        "Pierre-Auguste Renoir - Dance in the Country - Google Art Project.jpg"),
    ("renoir_girls_piano",       "Renoir — Young Girls at the Piano",    "Pierre-Auguste Renoir - Young Girls at the Piano - Google Art Project.jpg"),
    ("renoir_two_sisters",       "Renoir — Two Sisters (On the Terrace)","Pierre-Auguste Renoir - Two Sisters (On the Terrace) - Google Art Project.jpg"),
    ("renoir_garden_montmartre", "Renoir — The Garden in Montmartre",    "Pierre-Auguste Renoir - The Garden in Montmartre - Google Art Project.jpg"),

    # ── Degas (5) ─────────────────────────────────────────────────────────
    ("degas_little_dancer",      "Degas — Little Dancer of Fourteen",    "Edgar Degas - Little Dancer of Fourteen Years - Google Art Project.jpg"),
    ("degas_racehorses",         "Degas — Racehorses at Longchamp",      "Edgar Degas - Racehorses at Longchamp - Google Art Project.jpg"),
    ("degas_milliners",          "Degas — The Milliners",                "Edgar Degas - The Milliners - Google Art Project.jpg"),
    ("degas_cafe_concert",       "Degas — At the Café Concert",          "Edgar Degas - At the Café Concert - Google Art Project.jpg"),
    ("degas_dancers_bar",        "Degas — Dancers at the Bar",           "Edgar Degas - Dancers at the Bar - Google Art Project.jpg"),

    # ── Pissarro (5) ─────────────────────────────────────────────────────
    ("pissarro_red_roofs",       "Pissarro — Red Roofs",                 "Camille Pissarro - Red Roofs - Google Art Project.jpg"),
    ("pissarro_boulevard_morning","Pissarro — Boulevard Montmartre, Morning","Camille Pissarro - Boulevard Montmartre, Morning - Google Art Project.jpg"),
    ("pissarro_eragny",          "Pissarro — The Garden at Éragny",      "Camille Pissarro - The Garden at Éragny - Google Art Project.jpg"),
    ("pissarro_orchard_spring",  "Pissarro — Orchard in Spring",        "Camille Pissarro - Orchard in Spring - Google Art Project.jpg"),
    ("pissarro_haying_eragny",   "Pissarro — Haying at Éragny",          "Camille Pissarro - Haying at Éragny - Google Art Project.jpg"),

    # ── Sisley (4) ────────────────────────────────────────────────────────
    ("sisley_bridge_villeneuve", "Sisley — The Bridge at Villeneuve",    "Alfred Sisley - The Bridge at Villeneuve-la-Garenne - Google Art Project.jpg"),
    ("sisley_moret_sun",         "Sisley — Moret-sur-Loing in the Sun",  "Alfred Sisley - Moret-sur-Loing in the Sun - Google Art Project.jpg"),
    ("sisley_canal_saint_mammes","Sisley — The Canal of Saint-Mammès",   "Alfred Sisley - The Canal of Saint-Mammès - Google Art Project.jpg"),
    ("sisley_autumn_banks",      "Sisley — Autumn Banks of the Seine",   "Alfred Sisley - Autumn Banks of the Seine - Google Art Project.jpg"),

    # ── Morisot (4) ──────────────────────────────────────────────────────
    ("morisot_summer_day",       "Morisot — Summer's Day",               "Berthe Morisot - Summer's Day - Google Art Project.jpg"),
    ("morisot_reading",          "Morisot — Reading",                    "Berthe Morisot - Reading - Google Art Project.jpg"),
    ("morisot_cherry_tree",      "Morisot — The Cherry Tree",            "Berthe Morisot - The Cherry Tree - Google Art Project.jpg"),
    ("morisot_woman_dressing",   "Morisot — Woman at Her Toilette",      "Berthe Morisot - Woman at Her Toilette - Google Art Project.jpg"),

    # ── Cassatt (4) ──────────────────────────────────────────────────────
    ("cassatt_mother_child",     "Cassatt — Mother and Child",           "Mary Cassatt - Mother and Child - Google Art Project.jpg"),
    ("cassatt_opera",            "Cassatt — In the Loge",                 "Mary Cassatt - In the Loge - Google Art Project.jpg"),
    ("cassatt_tea_table",        "Cassatt — Lady at the Tea Table",          "Cassatt - Lady at the Tea Table - with frame.jpg"),
    ("cassatt_lilacs_window",    "Cassatt — Lilacs in a Window",         "Mary Cassatt - Lilacs in a Window - Google Art Project.jpg"),

    # ── Manet (4) ────────────────────────────────────────────────────────
    ("manet_olympia",            "Manet — Olympia",                       "Edouard Manet - Olympia - Google Art Project.jpg"),
    ("manet_garden_ruel",        "Manet — A Lane in the Garden at Rueil",   "Édouard Manet - Une allée de jardin de Rueil (RW 402).jpg"),
    ("manet_railroad",           "Manet — The Railway",                  "Edouard Manet - The Railway - Google Art Project.jpg"),
    ("manet_boating",            "Manet — Boating",                       "Edouard Manet - Boating - Google Art Project.jpg"),

    # ── Caillebotte (3) ──────────────────────────────────────────────────
    ("caillebotte_man_balcony",  "Caillebotte — Man on a Balcony",       "Gustave Caillebotte - Man on a Balcony - Google Art Project.jpg"),
    ("caillebotte_boating",      "Caillebotte — Boating on the Yerres",  "Gustave Caillebotte - Boating on the Yerres - Google Art Project.jpg"),
    ("caillebotte_orange_trees", "Caillebotte — Orange Trees",            "Gustave Caillebotte - Orange Trees - Google Art Project.jpg"),

    # ── Seurat (3) ────────────────────────────────────────────────────────
    ("seurat_circus",            "Seurat — The Circus",                  "Georges Seurat - The Circus - Google Art Project.jpg"),
    ("seurat_models",            "Seurat — Models (Poseuses)",           "Georges Seurat - Models - Google Art Project.jpg"),
    ("seurat_seine_grande_jatte","Seurat — The Seine at La Grande Jatte","Georges Seurat - The Seine at La Grande Jatte - Google Art Project.jpg"),

    # ── Cézanne (4) ──────────────────────────────────────────────────────
    ("cezanne_bathers",          "Cézanne — The Bathers",                "Paul Cézanne - The Bathers - Google Art Project.jpg"),
    ("cezanne_mont_sainte_large","Cézanne — Mont Sainte-Victoire (Large)","Paul Cézanne - Mont Sainte-Victoire - Google Art Project.jpg"),
    ("cezanne_still_life_curtain","Cézanne — Still Life with Curtain",   "Paul Cézanne - Still Life with Curtain - Google Art Project.jpg"),
    ("cezanne_house_provence",   "Cézanne — House in Provence",          "Paul Cézanne - House in Provence - Google Art Project.jpg"),

    # ── Gauguin (3) ──────────────────────────────────────────────────────
    ("gauguin_where_do_we_come", "Gauguin — Where Do We Come From?",     "Paul Gauguin - Where Do We Come From - Google Art Project.jpg"),
    ("gauguin_yellow_christ",    "Gauguin — The Yellow Christ",           "Paul Gauguin - The Yellow Christ - Google Art Project.jpg"),
    ("gauguin_tahitian_landscape","Gauguin — Tahitian Landscape",         "Paul Gauguin - Tahitian Landscape - Google Art Project.jpg"),

    # ── Van Gogh (5) ─────────────────────────────────────────────────────
    ("vangogh_cypresses",        "Van Gogh — Cypresses",                  "Vincent van Gogh - Cypresses - Google Art Project.jpg"),
    ("vangogh_night_cafe",       "Van Gogh — The Night Café",             "Vincent van Gogh - The Night Café - Google Art Project.jpg"),
    ("vangogh_roses",            "Van Gogh — Roses",                      "Vincent van Gogh - Roses - Google Art Project.jpg"),
    ("vangogh_olive_trees",      "Van Gogh — Olive Trees",                "Vincent van Gogh - Olive Trees - Google Art Project.jpg"),
    ("vangogh_starry_rhone",     "Van Gogh — Starry Night over the Rhône","Vincent van Gogh - Starry Night over the Rhône - Google Art Project.jpg"),

    # ── Sargent (3) ──────────────────────────────────────────────────────
    ("sargent_gondola",          "Sargent — A Gondola in Venice",         "John Singer Sargent - A Gondola in Venice - Google Art Project.jpg"),
    ("sargent_daughters_boit",   "Sargent — The Daughters of Edward Boit","John Singer Sargent - The Daughters of Edward Darley Boit - Google Art Project.jpg"),
    ("sargent_watercolours",     "Sargent — Watercolours",                "John Singer Sargent - Watercolours - Google Art Project.jpg"),

    # ── Sorolla (3) ───────────────────────────────────────────────────────
    ("sorolla_fishing",          "Sorolla — The Return from Fishing",     "Joaquín Sorolla - The Return from Fishing - Google Art Project.jpg"),
    ("sorolla_strolling_beach",  "Sorolla — Strolling along the Beach",   "Joaquín Sorolla - Strolling along the Beach - Google Art Project.jpg"),
    ("sorolla_children_sea",     "Sorolla — Children on the Sea",         "Joaquín Sorolla - Children on the Sea - Google Art Project.jpg"),

    # ── Hassam (3) ───────────────────────────────────────────────────────
    ("hassam_rue_daunou",        "Hassam — July Fourteenth, Rue Daunou",    "Childe Hassam, July Fourteenth, Rue Daunou, 1910.jpg"),
    ("hassam_rainy_boston",      "Hassam — Rainy Day, Boston",              "Childe Hassam - Rainy Day, Boston - Google Art Project.jpg"),
    ("hassam_poppies_isle",      "Hassam — Poppies on the Isle of Shoals","Childe Hassam - Poppies on the Isle of Shoals - Google Art Project.jpg"),
]


def url_for(commons_file: str) -> str:
    name = urllib.parse.quote(commons_file.replace(" ", "_"))
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width={WIDTH}"


def api_search(title_hint: str) -> str | None:
    q = urllib.parse.quote(f'{title_hint} filetype:bitmap')
    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           f"&list=search&srsearch={q}&srnamespace=6&srlimit=5")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        for hit in data.get("query", {}).get("search", []):
            name = hit["title"].removeprefix("File:")
            if name.lower().endswith((".jpg", ".jpeg", ".png")):
                return name
    except Exception:
        return None
    return None


def fetch(url: str, dest: Path | None) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            if r.status != 200:
                return False, f"HTTP {r.status}"
            data = r.read()
            if len(data) < 20000:
                return False, f"suspiciously small ({len(data)}B)"
            if dest:
                dest.write_bytes(data)
            return True, f"{len(data)//1024}KB"
    except Exception as e:
        return False, str(e)[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dest", default=str(Path.home() / "genius-tv" / "art"))
    args = ap.parse_args()

    dest_dir = Path(args.dest)
    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    ok, failed = [], []
    for local, title, cfile in ART:
        target = None if args.dry_run else dest_dir / f"{local}.jpg"
        if target and target.exists():
            print(f"  skip   {local:26} (already present)")
            ok.append((local, title))
            continue

        good, info = fetch(url_for(cfile), target)
        if not good and "404" in info:
            time.sleep(DELAY)
            hint = title.replace("—", " ")
            found = api_search(hint)
            if found:
                time.sleep(DELAY)
                good, info = fetch(url_for(found), target)
                if good:
                    info += "  [via search]"

        print(f"  {'ok ' if good else 'FAIL':6} {local:26} {info}")
        (ok if good else failed).append((local, title) if good else (local, cfile, info))
        time.sleep(DELAY)

    print(f"\n{len(ok)} succeeded, {len(failed)} failed")
    if failed:
        print("\nFAILED (fix the Commons filename):")
        for f in failed:
            print(f"  {f[0]:26} {f[1][:56]}  -> {f[2]}")

    if ok and not args.dry_run:
        print("\n--- paste into ART (append before the closing ]) ---")
        for i in range(0, len(ok), 3):
            print("        " + ", ".join(f'"{n}"' for n, _ in ok[i:i+3]) + ",")
        print("\n--- paste into ART_TITLES (append before the closing }) ---")
        for n, t in ok:
            print(f'        {n}: "{t}",')


if __name__ == "__main__":
    main()
