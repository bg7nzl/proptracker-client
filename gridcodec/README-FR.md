[English](README.md) | [中文](README-CN.md) | [日本語](README-JP.md) | [Français](README-FR.md)

---

# GridCodec

Codec binaire compact pour les matrices de propagation Maidenhead, conçu pour diffuser efficacement les données de propagation FT8/WSPR à de nombreux clients simultanément.

## Problème

Les modes numériques faibles comme le FT8 produisent de nombreux rapports de propagation. Une grille Maidenhead 4 caractères comporte 32 400 carreaux, soit une matrice d’adjacence brute 32 400×32 400 — environ **125 Mo** de bitmap. Diffuser cela en texte ou bitmap brut à des centaines de clients n’est pas réaliste.

GridCodec résout le problème par un algorithme de **projection dimensionnelle hiérarchique** qui exploite la sparsité géographique de la propagation. En pratique, l’activité FT8 typique se compresse en **~2–20 Ko**, soit une réduction d’au moins 10 000×.

## Algorithme

### Système de grille Maidenhead

Un locator Maidenhead 4 caractères (ex. `FN31`) code une position à la surface du globe.

| Caractère | Signification | Plage | Nombre |
| --------- | ------------- | ----- | ------ |
| 1er       | Champ lon     | A–R   | 18     |
| 2e        | Champ lat     | A–R   | 18     |
| 3e        | Carré lon     | 0–9   | 10     |
| 4e        | Carré lat     | 0–9   | 10     |

Cela donne 18×18 ＝ **324 champs**, chacun subdivisé en 10×10 ＝ **100 carreaux**, soit **32 400 carreaux** au total.

### Schéma d’indexation

```
field_index  = lon_field * 18 + lat_field        [0, 323]
square_index = lon_square * 10 + lat_square      [0, 99]
grid_index   = field_index * 100 + square_index  [0, 32399]
```

### Projection dimensionnelle hiérarchique

La matrice de propagation est une matrice d’adjacence binaire : l’élément (i, j) ＝ 1 signifie « les signaux émis depuis le carreau i sont reçus au carreau j ».

GridCodec ne stocke pas cette matrice telle quelle mais la décompose en deux couches et applique une **projection dimensionnelle** à chaque couche.

La projection dimensionnelle traite un bitmap 2D dont les indices de ligne/colonne se décomposent en (lon, lat) comme un tenseur 4D :

```
M[src_lon, src_lat, dst_lon, dst_lat]
```

Puis : (1) **calcule les masques de dimension** — un masque de bits par axe indiquant quelles valeurs de coordonnées participent à au moins un élément actif ; (2) **construit les bitmaps d’entrées** — dans la boîte définie par les masques, marque quelles combinaisons (lon, lat) sont réellement actives comme sources ou destinations ; (3) **construit la matrice interne** — la sous-matrice dense reliant uniquement les sources actives aux destinations actives.

Cela s’applique à deux niveaux :

- **Couche 1 (niveau champ) :** compresse la matrice de propagation 324×324 champ–champ.
- **Couche 2 (niveau carreau) :** pour chaque paire de champs active de la couche 1, compresse la sous-matrice 100×100 carreau–carreau.

Le résultat est un flux binaire auto-décrit, toutes les tailles étant dérivées des données déjà décodées — aucun champ de longueur explicite n’est nécessaire.

### Pourquoi ça marche

La propagation est géographiquement regroupée. Sur une bande FT8 typique :

- Seuls 30–60 des 324 champs sont actifs (la population radio amateur est concentrée en Amérique du Nord, Europe, Japon, etc.)
- Les champs actifs se regroupent le long de quelques bandes longitude/latitude
- Dans chaque paire de champs, seule une fraction des 10 000 chemins carreau–carreau possibles est active

La projection dimensionnelle capture directement cette structure : si seulement 5 des 18 valeurs de longitude et 4 des 18 de latitude sont actives, la boîte passe de 324 entrées à 20, et le bitmap d’entrées ne garde que les cellules vraiment actives.

## Format filaire (v1)

Tous les bitmaps multi-octets sont en **little-endian, LSB d’abord**. Le bit 0 de l’octet 0 est l’élément d’indice le plus bas.

### Structure globale

```
[En-tête : 2 octets] [Couche 1] [Couche 2 (optionnelle)]
```

### En-tête

| Octet | Champ   | Description                                                |
| ----- | ------- | ---------------------------------------------------------- |
| 0     | version | `0x01`                                                     |
| 1     | flags   | bit 0 : `has_layer2` (1 ＝ la couche 2 suit la couche 1)   |
|       |         | bits 1–7 : réservés, doivent être 0                        |

### Couche 1 : propagation au niveau champ

La couche 1 encode la propagation entre les 324 champs Maidenhead.

**Masques de dimension** (9 octets ＝ 4×18 bits ＝ 72 bits, packés) :

| Plage de bits | Masque          | Largeur  |
| ------------- | --------------- | -------- |
| 0–17          | src_lon_field   | 18 bits  |
| 18–35         | src_lat_field   | 18 bits  |
| 36–53         | dst_lon_field   | 18 bits  |
| 54–71         | dst_lat_field   | 18 bits  |

Le bit `i` est mis si l’index de coordonnée `i` participe à au moins un chemin actif.

**Bitmap champs source :**

- Taille : `ceil(popcount(src_lon) * popcount(src_lat) / 8)` octets
- Ordre ligne-majeur : longitude varie lentement, latitude rapidement
- Bit (i, j) ＝ 1 signifie que le champ en (active_src_lon[i], active_src_lat[j]) est une source active

**Bitmap champs destination :**

- Même disposition que le bitmap source, avec les masques destination

**Matrice interne :**

- Taille : `ceil(n_active_src_fields * n_active_dst_fields / 8)` octets
- Ordre ligne-majeur : source varie lentement, destination rapidement
- Bit (s, d) ＝ 1 signifie qu’il existe une propagation de active_src[s] vers active_dst[d]

### Couche 2 : détail au niveau carreau

Présente seulement si `flags & 0x01`. Pour chaque bit à 1 dans la matrice interne de la couche 1 (énumérée en ordre ligne-majeur), un sous-bloc suit.

Chaque sous-bloc a la même structure que la couche 1 mais utilise des masques de dimension 10 bits (lon_square, lat_square) :

**Masques de dimension carreau** (5 octets ＝ 4×10 bits ＝ 40 bits, packés) :

| Plage de bits | Masque           | Largeur  |
| ------------- | ---------------- | -------- |
| 0–9           | src_lon_square   | 10 bits  |
| 10–19         | src_lat_square   | 10 bits  |
| 20–29         | dst_lon_square   | 10 bits  |
| 30–39         | dst_lat_square   | 10 bits  |

Puis bitmap carreaux source, bitmap carreaux destination et matrice interne — structure identique à la couche 1 mais sur l’espace 100×100 carreaux.

## Compression et performances

Matrice pleine brute ＝ 32 400×32 400 bits ＝ **125 Mo**.

Le tableau ci-dessous combine les estimations théoriques et les résultats mesurés de la suite de tests C (GCC -O2, cœur x86-64 unique) :

| Scénario                           | Paires champs | Chemins grille | Taille encodée | Compression | Encode   | Décode   |
| ---------------------------------- | ------------- | -------------- | -------------- | ----------- | -------- | -------- |
| Bande calme                        | ~100          | ~1 000         | ~2 Ko         | ~64 000×    | —        | —        |
| Activité normale (500 chemins)\*   | 150           | 500            | 1,7 Ko         | ~78 700×    | 1,6 ms   | 0,2 ms   |
| Activité modérée (5 000 chemins)\* | 156           | 5 000          | 19,1 Ko       | ~6 700×     | 2,7 ms   | 0,4 ms   |
| Bande chargée (20 000 chemins)\*  | 156           | 20 000         | 105,6 Ko      | ~1 200×     | 3,1 ms   | 0,8 ms   |
| Dense — 10 % remplissage aléatoire\* | ~10 500     | ~10,5M         | 12,9 Mo        | ~9,7×       | 301 ms   | 131 ms   |
| Dense — 11 hotspots (Poisson)\*    | 46 955        | ~4,02M         | 4,0 Mo         | ~31×        | 801 ms   | 318 ms   |

\* Mesuré dans la suite de tests C. Les lignes sans timing sont des estimations d’ordre de grandeur.

**Scénario 11 hotspots :** 11 champs modélisant les centres de population radio amateur réels (FN NE USA, EM SE USA, DN centre US, JO Europe O, JN Europe S, IO UK/Irlande, PM Japon, QM Japon E, BN Canada O, LK Inde, OL Chine) avec activité à distribution de Poisson. Nœuds grille actifs : 8 131 ; densité : 0,38 % de la matrice pleine.

En typique FT8 réel (500–5 000 chemins), encode <3 ms et décode <0,5 ms — bien dans le cycle FT8 de 15 secondes.

> **Note :** La projection ajoute un petit surcoût par bloc (masques + bitmaps). En densité extrême (>50 % de remplissage), la sortie encodée peut dépasser la taille de la matrice brute. L’algorithme est optimisé pour les motifs clairsemés et géographiquement regroupés typiques de la propagation radio réelle.

## Implémentations

GridCodec dispose d’une implémentation C de référence et de ports dans quatre autres langages. Tous partagent le même format filaire v1 et sont testés en croisé (ex. toutes les implémentations non-C décodent le même payload de test généré par C et vérifient les résultats).

### C — Implémentation de référence

#### Bibliothèque single-header

Le codec entier est dans **`c/gridcodec.h`**, une bibliothèque C99 single-header sans dépendances externes au-delà de `<stdint.h>` et `<string.h>` (plus `<stdlib.h>` en mode desktop pour `malloc`).

**Modèle d’utilisation :**

```c
#include "gridcodec.h"            /* déclarations uniquement */

/* Dans exactement UN fichier .c : */
#define GRIDCODEC_IMPLEMENTATION
#include "gridcodec.h"            /* inclut les implémentations */
```

Toutes les fonctions sont `static`, chaque unité de compilation a sa propre copie, pas de conflits de linkeur.

#### Modes à la compilation

|                            | Défaut (desktop/serveur)        | `GC_EMBEDDED`           |
| -------------------------- | ------------------------------- | ----------------------- |
| Allocation mémoire         | Dynamique (`malloc` / `realloc`) | Statique uniquement (~13 Ko) |
| Support couche 2           | Encode + décode complets        | Ignorée au décode       |
| `gc_set` / `gc_encode`     | Disponibles                     | **Non compilés**        |
| `gc_free`                  | Disponible                      | **Non compilé**        |
| `gc_from`/`gc_to` (4 car.) | Résultats niveau grille         | Dégradé niveau champ   |
| `<stdlib.h>`               | Requis                          | **Non requis**          |
| `popcount`                 | `__builtin_popcount` (GCC/Clang) | Table de 256 octets    |

Activer le mode embarqué :

```c
#define GC_EMBEDDED
#define GRIDCODEC_IMPLEMENTATION
#include "gridcodec.h"
```

#### Référence API

**Initialisation et libération :**

```c
void gc_init(gc_matrix_t *m);
void gc_free(gc_matrix_t *m);   /* mode défaut uniquement */
```

**Enregistrement des chemins de propagation :**

```c
int gc_set(gc_matrix_t *m, const char *from4, const char *to4);
```

Enregistre un chemin entre deux grilles 4 caractères. Idempotent — les doublons sont gérés en interne par OU bit à bit. Retourne `0` en succès. Non disponible en mode `GC_EMBEDDED`.

**Encodage et décodage :**

```c
int gc_encode(const gc_matrix_t *m, uint8_t *buf, int cap);
int gc_decode(const uint8_t *data, int len, gc_matrix_t *m);
```

`gc_encode` retourne le nombre d’octets écrits (ou `GC_ERR_OVERFLOW`). Non disponible en mode `GC_EMBEDDED`.

`gc_decode` retourne le nombre d’octets consommés. En mode `GC_EMBEDDED`, les données de la couche 2 sont parsées (pour retourner le bon nombre d’octets) mais rejetées.

**Requêtes de propagation :**

```c
int gc_from(const gc_matrix_t *m, const char *grid, int *out, int max_out);
int gc_to(const gc_matrix_t *m, const char *grid, int *out, int max_out);
```

- Entrée 2 caractères (ex. `"FN"`) : retourne les indices champ (0–323)
- Entrée 4 caractères (ex. `"FN31"`) : en mode défaut indices grille (0–32399), en mode `GC_EMBEDDED` indices champ

`gc_from` retourne les destinations atteignables depuis la source donnée. `gc_to` retourne les sources qui peuvent atteindre la destination donnée.

**Conversion index/nom :**

```c
int  gc_field_index(const char *name);     /* "FN"   -> 0..323   */
void gc_field_name(int idx, char out[3]);  /* 0..323 -> "FN\0"   */
int  gc_grid_index(const char *name);      /* "FN31" -> 0..32399 */
void gc_grid_name(int idx, char out[5]);   /* 0..32399 -> "FN31\0" */
int  gc_grid_to_field(int grid_idx);
int  gc_grid_to_square(int grid_idx);
```

Toutes les entrées de noms sont insensibles à la casse.

**Codes d’erreur :**

| Constante            | Valeur | Signification                 |
| -------------------- | ------ | ----------------------------- |
| `GC_ERR_INVALID`     | -1     | Nom de grille invalide        |
| `GC_ERR_OVERFLOW`    | -2     | Tampon de sortie trop petit   |
| `GC_ERR_FORMAT`      | -3     | Données format filaire mal formées |
| `GC_ERR_CAPACITY`    | -4     | Échec d’allocation mémoire   |

#### Utilisation mémoire

**Mode défaut :**

| Composant               | Taille                              |
| ----------------------- | ----------------------------------- |
| Bitmap champs couche 1  | 13 122 octets (fixe)                |
| Métadonnées paires      | 38 octets (pointeurs + compteurs)   |
| Par paire de champs active | 1 254 octets (src + dst + bits carreaux) |

La mémoire totale croît linéairement avec le nombre de paires de champs actives :

| Paires actives | Mémoire totale |
| -------------- | -------------- |
| 0             | 12,9 Ko        |
| 64            | 91,2 Ko        |
| 256           | 326,4 Ko       |
| 1 024         | 1 266,9 Ko     |

**Mode embarqué :** fixe **13 122 octets** (12,8 Ko), pas d’allocation heap.

#### Construction et tests

Prérequis : compilateur C99 (GCC ou Clang recommandé), `make`.

```bash
cd c
make test
```

Compile et lance deux suites de tests :

1. **test_gridcodec** — mode défaut (desktop/serveur) : exactitude des helpers, aller-retour encode/décode, vérification des requêtes, débordement de tampon, scénarios réalistes (500 / 5 000 / 20 000 chemins), cas pire dense, tests extrêmes (10 % remplissage aléatoire, 11 hotspots Poisson).
2. **test_embedded** — mode `GC_EMBEDDED` : vérification de la taille mémoire statique, décode couche 1 seule, décode couche 1+2 (couche 2 correctement ignorée), dégradation des requêtes 4 car., absence à la compilation de l’API encode.

Sauter les tests extrêmes (utile sous Valgrind ou sur matériel lent) :

```bash
SKIP_EXTREME=1 ./test_gridcodec
```

Vérification des fuites mémoire :

```bash
gcc -g -O0 -std=c99 -o test_dbg test_gridcodec.c
SKIP_EXTREME=1 valgrind --leak-check=full ./test_dbg
```

Les deux modes ont été vérifiés sans fuite (0 erreur, tous les blocs heap libérés).

### Python

**Emplacement :** `python/` — paquet Python pur (`gridcodec`), support complet encode/décode/requêtes.

```bash
cd python && python3 test_gridcodec.py
```

### MicroPython

**Emplacement :** `micropython/` — fichier unique `gridcodec.py`, décode + requêtes uniquement. Les requêtes 4 car. se dégradent au niveau champ. Conçu pour ESP32, Pyboard, Raspberry Pi Pico, etc.

```bash
cd micropython && python3 test_gridcodec.py     # hôte
cd micropython && ./run_on_device.sh             # appareil via mpremote
```

### JavaScript

**Emplacement :** `js/` — Node.js et navigateur, encode/décode/requêtes complets.

```bash
cd js && node test_gridcodec.js
```

### Java

**Emplacement :** `java/gridcodec/` — Java 8+, encode/décode/requêtes complets.

```bash
cd java && javac -source 8 -target 8 gridcodec/*.java && java -cp . gridcodec.TestGridCodec
```

### Chaînes d’outils vérifiées

Toutes les implémentations ont été testées avec les chaînes d’outils suivantes :

| Langage        | Chaîne d’outils             | Version   | Notes                                                        |
| --------------- | --------------------------- | --------- | ------------------------------------------------------------ |
| **C**           | GCC                         | 13.3.0    | Mode défaut + embarqué, tous les tests passés                 |
| **Python**     | CPython                     | 3.12.3    | 500 chemins : ~12 Ko, encode ~470 ms, décode ~50 ms         |
| **MicroPython**| Pico (RP2040) mpremote      | 1.27.0    | L1 seul 14 B : ~87 ms/décode ; L1+L2 skip 30 B : ~3535 ms     |
| **JavaScript**  | Node.js                     | v18.19.1  | 500 chemins : ~12 Ko, encode ~6 ms, décode ~1 ms             |
| **Java**       | OpenJDK                     | 21.0.10   | 500 chemins : ~12 Ko, encode ~5 ms, décode ~1 ms             |

Interopérabilité inter-langages : les suites de tests Python, JavaScript et Java décodent chacune le même payload généré par C (couche 1 seule, FN↔PM, JO↔FN) et vérifient les résultats au niveau champ.

## Décisions de conception

**Bibliothèque header-only.** Simplifie l’intégration pour les bindings multi-langages. Les implémentations Python, MicroPython, JavaScript et Java sont livrées dans ce dépôt ; toutes partagent le même format filaire.

**Fonctions statiques.** Évite les conflits de symboles lorsque plusieurs unités de compilation incluent l’en-tête. Le compilateur élimine les fonctions inutilisées.

**Compilation dual-mode.** Les appareils embarqués (ex. ESP32, STM32) ont besoin d’une capacité décode seule sans heap. Le drapeau `GC_EMBEDDED` retire toute la logique d’encodage et la mémoire dynamique, donnant une empreinte statique d’environ 13 Ko adaptée aux stations réception seule.

**Recherche linéaire des paires.** `gc_set` et `gc_from`/`gc_to` utilisent une recherche linéaire sur les paires de champs. Avec des nombres de paires typiquement inférieurs à 500, c’est plus rapide que le surcoût d’une table de hachage. À 10 000+ paires (scénarios extrêmes), cela devient un coût mesurable (~800 ms encode) mais reste acceptable pour un encodage serveur par lots.

**`gc_set` idempotent.** Comme le décodage FT8 peut produire des rapports dupliqués dans une fenêtre de temps, `gc_set` est conçu pour être appelé répétitivement avec la même paire sans coût supplémentaire.

**Format filaire auto-décrit.** Chaque taille de champ est dérivée des données déjà décodées. Cela élimine les champs de longueur et rend le format robuste : un décodeur soit parse complètement le flux, soit retourne un code d’erreur.

## License

TBD
