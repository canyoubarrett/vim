import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE = Path(__file__).parent
OUT = HERE.parent
exe = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--chrome=")), None)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    for slug in ("tidal-shuffle-operation-card", "tidal-shuffle-manual"):
        pg = b.new_page(viewport={"width": 864, "height": 1100}, device_scale_factor=2)
        pg.goto((HERE / f"{slug}.html").as_uri(), wait_until="load")
        pg.evaluate("document.fonts.ready")
        fams = pg.evaluate("Array.from(document.fonts).filter(f => f.status === 'loaded').map(f => f.family)")
        # anything that does not fit its page
        over = pg.evaluate("""Array.from(document.querySelectorAll('.page')).map((p, i) => {
            const foot = p.querySelector('.run-foot'); const limit = foot ? foot.offsetTop - 8 : p.clientHeight - 40;
            let bottom = 0; for (const el of p.children) { if (el.classList.contains('watermark') || el.classList.contains('run-foot') || el.classList.contains('run-head')) continue;
              bottom = Math.max(bottom, el.offsetTop + el.offsetHeight); }
            return [i + 1, bottom, limit]; }).filter(x => x[1] > x[2])""")
        wide = pg.evaluate("Array.from(document.querySelectorAll('.fig')).filter(f => f.scrollWidth > f.clientWidth + 1).length")
        pg.emulate_media(media="print")
        pg.pdf(path=str(OUT / f"{slug}.pdf"), width="8.5in", height="11in", print_background=True, prefer_css_page_size=True)
        n = pg.evaluate("document.querySelectorAll('.page').length")
        if "--shots" in sys.argv:
            pg.emulate_media(media="screen")
            for i, el in enumerate(pg.query_selector_all(".page")):
                el.screenshot(path=str(HERE / f"shot-{slug}-{i + 1:02d}.png"))
        print(slug, "pages", n, "overflow", over, "wide figs", wide, sorted(set(fams)))
    b.close()
