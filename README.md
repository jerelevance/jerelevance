# Jerelevance

Drop a report into `reports/` and the site rebuilds itself within a minute or two.

- **Title:** the HTML page's `<title>`, or the PDF's title, or the filename.
- **Comment:** the page's `<meta name="description">`, or a `.txt` file with the same name (`skynet.pdf` + `skynet.txt`).
- **Date:** when the file was added.
- **Overrides:** put anything you want to force in `reports/_meta.json`.

Don't edit `index.html` directly; edit `template.html` for design changes.
