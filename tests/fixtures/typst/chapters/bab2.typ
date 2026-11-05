// =====================================================================
//  BAB 2 — METODE
// =====================================================================
#import "../template.typ": *

= Metode

== Dataset <sec:2.1>

Karakteristik dataset dirangkum pada @tab:1.data.

#thesis-table(
  caption: [Karakteristik dataset],
  label: <tab:1.data>,
  columns: (auto, auto, auto, 4cm),
  align: (left, right, right, left),
  header: (
    [*Subset*],
    [*Jumlah*],
    [*Proporsi (%)*],
    [*Keterangan*],
  ),
  rules: (2,),
  [Kelas A], [X.XXX], [XX,X], [Deskripsi],
  [Kelas B], [X.XXX], [XX,X], [Deskripsi],
  [*Total*], [X.XXX], [100,0], [],
)

== Tabel Lebar <sec:2.2>

#landscape[
  #thesis-table(
    caption: [Rekapitulasi],
    label: <tab:2.rekap>,
    columns: (auto, auto),
    align: (left, right),
    header: ([*Kategori*], [*Nilai*]),
    [A], [1,5],
    [B], [2,5],
  )
]
