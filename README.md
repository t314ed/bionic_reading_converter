# bionic-pdf

Convertit le texte d'un PDF au format **bionic reading** : le début de chaque
mot est mis en gras pour guider l'œil.

> **L**e **convert**isseur **pre**nd **u**n **fich**ier **P**DF **e**t **modi**fie
> **uniqu**ement **l**a **mi**se **e**n **for**me **d**u **tex**te.

Le contenu ne change pas : mêmes mots, mêmes polices, mêmes positions. Les
figures ne sont pas modifiées. Le français et l'anglais sont pris en charge
automatiquement, sans option à choisir.

## Installation

Il faut Python 3.9 ou plus récent. Dans un environnement virtuel Python :

```bash
git clone https://github.com/t314ed/bionic_reading_converter.git
cd bionic_reading_converter
pip install .
```

Dépendance unique : [PyMuPDF](https://pymupdf.readthedocs.io), installée
automatiquement. Pour modifier le code, utilise plutôt `pip install -e .` : les
changements sont pris en compte sans réinstaller.

## Utilisation

1. Active l'environnement Python où le convertisseur est installé. C'est à
   refaire dans chaque nouveau terminal :

   ```bash
   source /chemin/vers/ton/env/bin/activate
   ```

2. Lance la conversion :

   ```bash
   bionic-pdf ~/Documents/mon_article.pdf
   ```

   Le résultat est créé à côté de l'original, sous le nom
   `mon_article_bionic.pdf`. L'original n'est jamais modifié.

### Dossiers `source/` et `converti/`

Le dépôt contient deux dossiers de travail. Leur contenu n'est jamais envoyé
sur GitHub (voir `.gitignore`) :

- `source/` : les PDF à convertir ;
- `converti/` : les PDF convertis.

```bash
bionic-pdf source/mon_article.pdf -o converti/mon_article.pdf
```

### Options

```bash
bionic-pdf article.pdf -o lecture.pdf     # choisit le nom du fichier produit
bionic-pdf article.pdf --pages 1-3,5      # convertit seulement certaines pages
bionic-pdf article.pdf --ratio 0.4        # met moins de lettres en gras (défaut : 0.5)
bionic-pdf article.pdf --weight 0.06      # gras plus épais (défaut : 0.04)
bionic-pdf article.pdf -q                 # n'affiche pas le résumé
bionic-pdf --help                         # aide complète
```

Depuis le dossier du dépôt, `python -m bionic_pdf ...` marche aussi sans
installation (PyMuPDF doit quand même être installé).

### Le résumé

À la fin, la commande affiche :

- le nombre de pages traitées et de mots convertis ;
- ce qui a été laissé tel quel : figures, texte déjà en gras, formules,
  texte non horizontal ;
- les pages éventuellement remises d'origine par sécurité, si la vérification
  a détecté un écart.

Si le résumé indique « aucun texte converti », le PDF est probablement scanné :
ses pages sont des images, sans texte à convertir.

## Règles de mise en gras

| Longueur du mot | Lettres en gras |
|---|---|
| 1 à 3 | 1 |
| 4 | 2 |
| 5 et plus | la moitié, arrondie au-dessus (`--ratio`) |

- **Français** : les élisions sont séparées (« **l**'**arb**re », « **q**u'**i**l »),
  les accents et « œ » comptent comme des lettres.
- **Anglais** : les contractions restent un seul mot (« **do**n't », « **we**'ll »).
- Les nombres seuls (2027, 16,2 %) ne sont jamais modifiés.
- Les mots composés sont traités partie par partie (« **fau**lt-**fr**ee »).

## Ce qui n'est jamais modifié

- les **figures** : images, schémas vectoriels et leurs étiquettes ;
- le texte **déjà en gras** (titres, en-têtes de tableaux) ;
- les **formules mathématiques** (en gras, une variable change de sens) ;
- le texte **incliné ou vertical** ;
- le texte dont la police ne peut pas être réutilisée.

## Fonctionnement

1. Lecture de chaque caractère : police, taille, couleur, position exacte.
2. Calcul des lettres à mettre en gras, mot par mot ([text.py](bionic_pdf/text.py)).
3. Repérage des figures ([figures.py](bionic_pdf/figures.py)).
4. Effacement du texte concerné, sans toucher aux images ni aux dessins, puis
   réécriture au même endroit avec **les polices déjà présentes dans le PDF**
   ([fonts.py](bionic_pdf/fonts.py)). Aucune police n'est ajoutée : tous les
   lecteurs (Evince, Okular, Firefox, Acrobat…) affichent le résultat comme
   l'original. Le gras est obtenu en ajoutant un fin contour de la couleur du
   texte : la largeur des lettres ne change pas, donc la mise en page reste
   identique au point près.
5. **Vérification** : chaque page doit contenir exactement les mêmes caractères,
   aux mêmes positions. Sinon, la page d'origine est remise telle quelle et le
   résumé le signale. Le texte reste sélectionnable et le copier-coller donne le
   texte d'origine. Les liens cliquables sont conservés.

## Limites

- Les **PDF scannés** (pages en image) ne contiennent pas de texte : rien n'est
  converti. Il faudrait d'abord une reconnaissance de texte (OCR).
- Le texte dont la police ne décrit pas ses caractères (ni table ToUnicode, ni
  encodage connu) est laissé tel quel : le résumé l'indique.
- Les figures sont détectées automatiquement. Une étiquette isolée loin de sa
  figure peut quand même être convertie.

## Tests

```bash
pip install -e ".[test]"
pytest
```
