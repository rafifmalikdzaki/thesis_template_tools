// =====================================================================
//  BAB 1 — PENDAHULUAN
// =====================================================================
#import "../template.typ": *

= Pendahuluan

== Latar Belakang <sec:1.1>

Penelitian ini memakai pendekatan _eksperimental_ dan _kuantitatif_
dengan `contoh` kode. Lihat @fig:1.alur dan
@tab:1.data serta @eq:1.f1 dan Bab @sec:2.1.

#thesis-figure(
  "assets/fig-1.pdf",
  caption: [Alur penelitian],
) <fig:1.alur>

== Rumusan Masalah <sec:1.2>

Rumusan masalah penelitian adalah sebagai berikut:

+ Bagaimana [masalah pertama]?
+ Bagaimana [masalah kedua]?

#equation-row[
  $ F_1 = 2 dot frac("Presisi" times "Recall", "Presisi" + "Recall") $ <eq:1.f1>
]

== Implementasi <sec:1.3>

Kode sumber ditunjukkan pada @lst:1.kode.

#listing([Fungsi kunci])[
```python
def f(x):
    return x + 1
```
] <lst:1.kode>
