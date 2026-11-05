// =====================================================================
//  LAMPIRAN A — DATA PENDUKUNG
// =====================================================================
#import "../template.typ": *

= Data Pendukung <lam:a>

== Contoh <lam:a.1>

Tabel @tab:lam.a1 dan Persamaan @eq:lam.a1.

#thesis-table(
  caption: [Data pendukung],
  label: <tab:lam.a1>,
  columns: (auto, auto),
  align: (left, right),
  header: ([*Pengamatan*], [*Nilai*]),
  [Pengamatan 1], [X,XX],
  [Pengamatan 2], [X,XX],
)

#equation-row[
  $ bar(x) = frac(1, n) sum_(i=1)^n x_i $ <eq:lam.a1>
]
