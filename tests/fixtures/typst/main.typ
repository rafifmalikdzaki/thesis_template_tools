// =====================================================================
//  FIXTURE MASTER — Typst
// =====================================================================
#import "template.typ": *

#show: thesis

#cover-page()

#set page(numbering: "i")
#counter(page).update(1)

#approval-page()
#declaration-page()
#include "frontmatter/abstrak.typ"

#outline-page("Daftar Isi", target: heading, depth: 2)
#outline-page("Daftar Gambar", target: figure.where(kind: image), depth: 1)
#outline-page("Daftar Tabel", target: figure.where(kind: table), depth: 1)
#outline-page("Daftar Kode Sumber", target: figure.where(kind: raw), depth: 1)

#set page(numbering: "1")
#counter(page).update(1)

#include "chapters/bab1.typ"
#include "chapters/bab2.typ"

#include "backmatter/referensi.typ"

#appendix()
#include "lampiran/lampiran_a.typ"
