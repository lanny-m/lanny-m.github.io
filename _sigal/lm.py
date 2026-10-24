#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lm — карточки товаров lanny-m.github.io (sigal).

КОМАНДЫ
  lm add   ФОТО ТОВАР ЦЕНА [ТОВАР ЦЕНА ...] [ФОТО2 ТОВАР ЦЕНА ...]
      Каждое фото открывает новую карточку, за ним пары "товар цена"
      (в карточке может быть 2 и больше товаров). Фото копируется в
      _sigal/images/IMG_ГГ_NN.JPG (ГГ = год, NN = следующий свободный номер),
      рядом пишется IMG_ГГ_NN.md. Если артикул уже есть в другой карточке,
      печатается предупреждение, добавление не блокируется.

  lm price АРТИКУЛ=ЦЕНА [АРТИКУЛ=ЦЕНА ...]      (или: АРТИКУЛ ЦЕНА ...)
      Меняет цену во ВСЕХ карточках, где встречается артикул (дубли тоже).
      Если хоть один артикул не найден — ничего не меняется.

  lm del   АРТИКУЛ|КАРТОЧКА [...]
      Артикул: убирает этот товар из всех карточек, где он есть. Если в
      карточке остались другие товары, фото остаётся; если не осталось —
      карточка удаляется целиком. КАРТОЧКА (IMG_26_31) — удалить целиком.
      Целиком = .md + исходник в _sigal/images + копия в корне + thumbnails/.

  lm list  [АРТИКУЛ ...]        все карточки или только с этими артикулами
  lm build                      только sigal build, без изменений
  lm clean                      удалить в корне и thumbnails/ картинки,
                                у которых нет исходника в _sigal/images

ФЛАГИ (в любом месте)
  -n   только показать план, ничего не менять
  -c   после сборки сделать git commit (по умолчанию коммита нет,
       сообщение для коммита печатается в конце)
  -p   commit + git push (push пока работает только из GitKraken)
  -h   эта справка

ПРАВИЛА
  Товар:   "Бюстгальтер 11961". Сокращения: "б 11961" -> Бюстгальтер,
           "т 51961" -> Трусики.
  Цена:    число, либо "-" или "нет" -> "нет в наличии".
  Артикул: ищется как отдельное слово в строке товара, регистр не важен:
           11593 находит "Бюстгальтер 11593", но НЕ "11593-2";
           в строке "Бюстгальтер 11816, 8656" находятся и 11816, и 8656.
  Коммит:  сообщение в стиле "add/edit/del <артикулы>"; в коммит попадают
           только _sigal/images, index.html, thumbnails/, static/ и IMG_* в
           корне. С -c/-p перед началом проверяется, что в этих путях нет
           незакоммиченных изменений.

ПРИМЕРЫ
  lm add ~/Downloads/a.jpg "б 11961" 295 "т 51961" 120 ~/Downloads/b.jpg "б 11002A" 320
  lm -c add ~/Downloads/a.jpg "Бюстгальтер 11961" 295
  lm price 11961=310 51961=нет
  lm del 11961 51961 IMG_26_31
  lm -n del 11593                 # посмотреть, что будет удалено
  lm list 11593
"""

import datetime
import os
import re
import shutil
import subprocess
import sys

SIGAL_DIR = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(SIGAL_DIR)
IMAGES = os.path.join(SIGAL_DIR, 'images')
THUMBS = os.path.join(ROOT, 'thumbnails')

IMG_EXTS = ('.jpg', '.jpeg', '.png')
CARD_RE = re.compile(r'^IMG_(\d\d)_(\d+)$')
NA = 'нет в наличии'
ALIASES = {'б': 'Бюстгальтер', 'b': 'Бюстгальтер', 'т': 'Трусики', 't': 'Трусики'}
# пути, которыми управляет скрипт (только они попадают в коммит)
GIT_PATHS = ['_sigal/images', 'index.html', 'thumbnails', 'static', 'IMG_*']

DRY = False


def die(msg):
    print('ОШИБКА: ' + msg, file=sys.stderr)
    sys.exit(1)


def act(desc, fn=None):
    print(('  [план] ' if DRY else '  ') + desc)
    if fn and not DRY:
        fn()


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMG_EXTS


def tokens(item):
    return [t.strip(',;').lower() for t in item.split()]


def norm_price(s):
    s = s.strip()
    if s.lower() in ('-', '—', 'нет', 'no', 'na', 'n/a', '0'):
        return NA
    return s


def norm_item(s):
    parts = s.split()
    if len(parts) >= 2 and parts[0].lower() in ALIASES:
        parts[0] = ALIASES[parts[0].lower()]
    return ' '.join(parts)


class Card:
    def __init__(self, name):
        self.name = name
        self.md = os.path.join(IMAGES, name + '.md')
        self.items = []   # [[товар, цена], ...]
        self.extra = []   # прочие строки .md, сохраняются как есть

    def load(self):
        items, prices = [], []
        with open(self.md, encoding='utf-8') as fh:
            for line in fh.read().splitlines():
                if line.startswith('item:'):
                    items.append(line[5:].strip())
                elif line.startswith('price:'):
                    prices.append(line[6:].strip())
                elif line.strip():
                    self.extra.append(line)
        if len(items) != len(prices):
            die('%s: товаров %d, цен %d' % (self.md, len(items), len(prices)))
        self.items = [[i, p] for i, p in zip(items, prices)]
        return self

    def text(self):
        return '\n'.join(['item: ' + i for i, _ in self.items]
                         + ['price: ' + p for _, p in self.items]
                         + self.extra)

    def save(self):
        with open(self.md, 'w', encoding='utf-8') as fh:
            fh.write(self.text())

    def source(self):
        for f in os.listdir(IMAGES):
            stem, ext = os.path.splitext(f)
            if stem == self.name and ext.lower() in IMG_EXTS:
                return os.path.join(IMAGES, f)
        return None

    def generated(self):
        out = []
        for d in (ROOT, THUMBS):
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                stem, ext = os.path.splitext(f)
                if stem == self.name and ext.lower() in IMG_EXTS:
                    out.append(os.path.join(d, f))
        return out

    def matches(self, art):
        art = art.lower()
        return [i for i, (item, _) in enumerate(self.items) if art in tokens(item)]

    def __str__(self):
        return '%s  %s' % (self.name, ' | '.join('%s = %s' % (i, p) for i, p in self.items))


def load_cards():
    cards = []
    for f in sorted(os.listdir(IMAGES)):
        stem, ext = os.path.splitext(f)
        if ext == '.md' and CARD_RE.match(stem):
            cards.append(Card(stem).load())
    return cards


def find(cards, art):
    """[(card, idx), ...] для всех вхождений артикула."""
    return [(c, i) for c in cards for i in c.matches(art)]


def next_number():
    yy = datetime.date.today().strftime('%y')
    pat = re.compile(r'^IMG_%s_(\d+)\.' % yy, re.I)
    mx = 0
    for d in (IMAGES, ROOT, THUMBS):
        for f in os.listdir(d):
            m = pat.match(f)
            if m:
                mx = max(mx, int(m.group(1)))
    return yy, mx + 1


def rel(p):
    return os.path.relpath(p, ROOT)


# ---------------------------------------------------------------- команды

def cmd_add(args, cards):
    # разбор: ФОТО ТОВАР ЦЕНА [ТОВАР ЦЕНА ...] [ФОТО ...]
    groups = []
    i = 0
    while i < len(args):
        a = args[i]
        if is_image(a):
            if not os.path.isfile(a):
                die('файл не найден: ' + a)
            groups.append([a, []])
            i += 1
            continue
        if not groups:
            die('сначала укажите файл фото, потом товары: ' + a)
        if i + 1 >= len(args):
            die('нет цены для товара: ' + a)
        groups[-1][1].append([norm_item(a), norm_price(args[i + 1])])
        i += 2
    if not groups:
        die('нечего добавлять')
    for photo, items in groups:
        if not items:
            die('нет товаров для фото ' + photo)
        for item, _ in items:
            for tok in tokens(item):
                dup = [c.name for c, _ in find(cards, tok)] if re.search(r'\d', tok) else []
                if dup:
                    print('  внимание: %s уже есть в %s' % (tok, ', '.join(dup)))

    yy, n = next_number()
    arts = []
    for photo, items in groups:
        name = 'IMG_%s_%02d' % (yy, n)
        n += 1
        ext = os.path.splitext(photo)[1].lower()
        ext = '.JPG' if ext in ('.jpg', '.jpeg') else ext
        card = Card(name)
        card.items = items
        dst = os.path.join(IMAGES, name + ext)
        act('%s  <-  %s' % (rel(dst), photo), lambda s=photo, d=dst: shutil.copy2(s, d))
        act('%s: %s' % (rel(card.md), ' | '.join('%s = %s' % (i, p) for i, p in items)), card.save)
        arts += [tokens(i)[-1] for i, _ in items]
    return 'add ' + ' '.join(arts)


def cmd_price(args, cards):
    pairs = []
    i = 0
    while i < len(args):
        if '=' in args[i]:
            art, price = args[i].split('=', 1)
            i += 1
        else:
            if i + 1 >= len(args):
                die('нет цены для ' + args[i])
            art, price = args[i], args[i + 1]
            i += 2
        pairs.append((art.strip(), norm_price(price)))
    if not pairs:
        die('укажите АРТИКУЛ=ЦЕНА')

    plan = []
    for art, price in pairs:
        hits = find(cards, art)
        if not hits:
            die('артикул не найден: ' + art)
        for card, idx in hits:
            plan.append((card, idx, price))

    touched = set()
    for card, idx, price in plan:
        item, old = card.items[idx]
        card.items[idx][1] = price
        act('%s: %s  %s -> %s' % (card.name, item, old, price))
        touched.add(card)
    for card in touched:
        act('сохранить ' + rel(card.md), card.save)
    return 'edit ' + ' '.join(a for a, _ in pairs)


def cmd_del(args, cards):
    if not args:
        die('укажите артикулы или карточки')
    by_name = {c.name: c for c in cards}
    remove_cards = {}     # name -> card (целиком)
    remove_items = {}     # name -> set(idx)
    for a in args:
        key = os.path.splitext(os.path.basename(a))[0]
        if key in by_name:
            remove_cards[key] = by_name[key]
            continue
        hits = find(cards, a)
        if not hits:
            die('не найдено: ' + a)
        for card, idx in hits:
            remove_items.setdefault(card.name, set()).add(idx)

    # карточка, из которой удаляются все товары, удаляется целиком
    for name, idxs in list(remove_items.items()):
        card = by_name[name]
        if len(idxs) >= len(card.items):
            remove_cards[name] = card
            del remove_items[name]
    for name in remove_cards:
        remove_items.pop(name, None)

    def rm(p):
        return lambda: os.remove(p)

    for name, idxs in sorted(remove_items.items()):
        card = by_name[name]
        for idx in sorted(idxs, reverse=True):
            act('%s: убрать %s' % (name, card.items[idx][0]))
            del card.items[idx]
        act('сохранить %s (осталось: %s)' % (rel(card.md), ' | '.join(i for i, _ in card.items)), card.save)

    for name, card in sorted(remove_cards.items()):
        act('удалить карточку %s (%s)' % (name, ' | '.join(i for i, _ in card.items)))
        paths = [card.md, card.source()] + card.generated()
        for p in paths:
            if p and os.path.exists(p):
                act('  rm ' + rel(p), rm(p))
    return 'del ' + ' '.join(args)


def cmd_clean(args, cards):
    known = {c.name for c in cards}
    known |= {os.path.splitext(f)[0] for f in os.listdir(IMAGES) if is_image(f)}
    n = 0
    for d in (ROOT, THUMBS):
        for f in sorted(os.listdir(d)):
            stem = os.path.splitext(f)[0]
            if is_image(f) and CARD_RE.match(stem) and stem not in known:
                p = os.path.join(d, f)
                act('rm ' + rel(p), lambda p=p: os.remove(p))
                n += 1
    if not n:
        print('  сирот нет')
        return None
    return 'clean %d orphan files' % n


def cmd_list(args, cards):
    if not args:
        for c in cards:
            print(c)
        return
    for a in args:
        hits = find(cards, a)
        if not hits:
            print('%s: не найдено' % a)
        for card, idx in hits:
            print('%s  %s = %s' % (card.name, *card.items[idx]))


# ---------------------------------------------------------------- git / sigal

def git(*a, **kw):
    return subprocess.run(['git'] + list(a), cwd=ROOT, text=True, **kw)


def check_clean():
    r = git('status', '--porcelain', '--', *GIT_PATHS, capture_output=True)
    if r.stdout.strip():
        die('есть незакоммиченные изменения в файлах сайта, сначала разберитесь с ними '
            '(или запустите без -c):\n' + r.stdout)


def build():
    exe = shutil.which('sigal') or os.path.expanduser('~/.local/bin/sigal')
    if not os.path.exists(exe):
        die('не найден sigal')
    act('sigal build')
    if DRY:
        return
    r = subprocess.run([exe, 'build'], cwd=SIGAL_DIR)
    if r.returncode:
        die('sigal build завершился с ошибкой %d' % r.returncode)


def commit(msg, push):
    act('git add ' + ' '.join(GIT_PATHS))
    if DRY:
        act('git commit -m "%s"' % msg)
        if push:
            act('git push')
        return
    git('add', '-A', '--', *GIT_PATHS, check=True)
    if git('diff', '--cached', '--quiet').returncode == 0:
        print('  нечего коммитить')
        return
    git('commit', '-q', '-m', msg, check=True)
    print('  commit: ' + git('log', '-1', '--oneline', capture_output=True).stdout.strip())
    if push:
        act('git push')
        if git('push').returncode:
            die('git push не удался; отправьте через GitKraken')


# ---------------------------------------------------------------- main

def main(argv):
    global DRY
    flags = [a for a in argv if a.startswith('-') and len(a) == 2 and a[1] in 'ncph']
    args = [a for a in argv if a not in flags]
    DRY = '-n' in flags
    push = '-p' in flags
    do_commit = '-c' in flags or push
    if not args or '-h' in flags or args[0] in ('help', '--help'):
        print(__doc__)
        return
    cmd, args = args[0], args[1:]

    if cmd == 'build':
        build()
        return
    cards = load_cards()
    if cmd == 'list':
        cmd_list(args, cards)
        return
    fn = {'add': cmd_add, 'price': cmd_price, 'del': cmd_del, 'clean': cmd_clean}.get(cmd)
    if not fn:
        die('неизвестная команда: %s\n%s' % (cmd, __doc__))

    if do_commit:
        check_clean()
    msg = fn(args, cards)
    if msg is None:
        return
    build()
    if do_commit:
        commit(msg, push)
    else:
        print('  (без коммита; сообщение для коммита: %s)' % msg)


if __name__ == '__main__':
    main(sys.argv[1:])
