// Fixture Typst layout: the helper interface, minimal implementations.
#let meta = json("metadata.json")

#let attach-label = label
#let thesis(body) = body
#let appendix() = none
#let landscape(body) = body
#let outline-page(title, target: heading, depth: 2) = none

#let thesis-figure(path, caption: none) = figure(
  image(path),
  caption: caption,
  supplement: [Gambar],
)

#let thesis-table(
  caption: none,
  label: none,
  columns: auto,
  align: auto,
  header: (),
  rules: (),
  ..cells,
) = figure(
  table(columns: columns, ..header, ..cells.pos()),
  caption: caption,
  supplement: [Tabel],
)

#let listing(caption, body) = figure(
  body,
  caption: caption,
  supplement: [Kode Sumber],
)

#let equation-row(body) = body
#let thesis-bibliography(body) = body
#let cover-page() = none
#let approval-page() = none
#let declaration-page() = none
