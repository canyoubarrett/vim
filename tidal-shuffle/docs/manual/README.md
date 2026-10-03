# Tidal Shuffle manuals (Alter Era)

* `tidal-shuffle-operation-card.pdf`: the one-page operation card (AE-TS-00).
* `tidal-shuffle-manual.pdf`: the engineering and operation manual, 15 pages (AE-TS-01).

Both are US Letter, set in the house style of
[diagram-design](https://github.com/cathrynlavery/diagram-design) with an Alter Era skin
(warm greys, one orange, Inter Tight and Geist Mono), with the Alter Era mark as a watermark.

To rebuild after a change (`build.py` needs only Python 3; `render.py` needs Playwright):

```bash
cd docs/manual/src
python3 build.py                 # writes the two HTML files
python3 render.py                # prints them to ../*.pdf (needs `pip install playwright`)
```

The fonts (Inter Tight and Geist Mono, both SIL Open Font License) are embedded from `fonts.css`.
