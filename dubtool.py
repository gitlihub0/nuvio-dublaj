#!/usr/bin/env python3
"""Tarif (dublaj_kaynaklari.json) hata ayıklama aracı.

Uygulamadaki DubPipelineRunner ile aynı adım mantığını bilgisayarında çalıştırır ve her adımın
sonucunu gösterir. Yeni bir site eklerken APK'ya dokunmadan tarifi burada denersin.

Örnekler:
  # Tam akış: arama + sonuç seçimi + adımlar (gerçek istekler atar)
  python3 dubtool.py --provider fullhdfilmizlesene --imdb tt1375666 --title "Inception" --duration 148

  # Dizi
  python3 dubtool.py --provider SITE --series --title "Dizi Adı" --season 1 --episode 2

  # Arama atlanır, tek bir film sayfasından başlanır (adımları ayıklamak için)
  python3 dubtool.py --provider SITE --page https://site.com/film/ornek/ --duration 120

  # Kaydettiğin bir arama sonucu HTML'inde search.pick regex'lerini dene
  python3 dubtool.py --provider SITE --test-pick arama_sonucu.html

Not: Python regex'i Java'dakine çok benzer ama birebir aynı değil. Egzotik özellikleri
(possessive, atomik gruplar, \\p{..}) kullanma.
"""
import argparse, base64, codecs, json, re, sys, urllib.parse, urllib.request

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Mobile Safari/537.36")
MAX_BODY = 3 * 1024 * 1024


# ---- işlemler (DubOps.kt ile aynı) -------------------------------------------------------
def rot13(s): return codecs.decode(s, "rot13")


def b64_lenient(s, charset):
    out = []
    for c in s:
        if c.isascii() and (c.isalnum() or c in "+/"): out.append(c)
        elif c == "-": out.append("+")
        elif c == "_": out.append("/")
    if len(out) % 4 == 1: out.pop()
    while len(out) % 4: out.append("=")
    return base64.b64decode("".join(out)).decode(charset, errors="replace")


def shift_key(s, key, mod, add, sub):
    if not key or mod <= 0: return s
    r = []
    for i, ch in enumerate(s):
        v = ord(ch) & 0xFF
        off = ord(key[i % len(key)]) % mod + add
        r.append(chr((v - off if sub else v + off) & 0xFFFF))
    return "".join(r)


def json_path(text, path):
    node = json.loads(text)
    for key, idx in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path):
        node = node[key] if key else node[int(idx)]
    return node if isinstance(node, str) else json.dumps(node)


def expand(t, vars_, strict):
    miss = [False]

    def sub(m):
        v = vars_.get(m.group(1))
        if not v:
            miss[0] = True
            return ""
        return v
    r = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, t)
    return None if strict and miss[0] else r


def request_vars(req):
    v = {}
    if req.get("imdb"): v["imdb"] = req["imdb"]
    if req.get("title"):
        v["title_raw"] = req["title"]
        v["title"] = re.sub(r"\s+\(\d{4}\)$", "", req["title"]).strip()
    for k in ("year", "season", "episode", "durationMin"):
        if req.get(k) is not None: v[k] = str(req[k])
    return v


def live_fetch(url, referer, headers):
    if not url.startswith("https://"):
        raise ValueError("sadece https desteklenir: " + url)
    h = {"User-Agent": UA, **headers}
    if referer: h["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        return r.read(MAX_BODY).decode("utf-8", errors="replace")


class Runner:
    def __init__(self, fetch=live_fetch, verbose=True):
        self.fetch, self.verbose = fetch, verbose

    def say(self, msg):
        if self.verbose: print(msg)

    def pick_candidates(self, html, p):
        found = []
        for pat in p["search"]["pick"]:
            for m in re.finditer(pat, html, re.S | re.I):
                href = (m.group(1) or "").strip()
                if not href: continue
                if href.startswith(("http://", "https://")): u = href
                elif href.startswith("//"): u = "https:" + href
                elif href.startswith("/"): u = p["base"].rstrip("/") + href
                else: u = p["base"].rstrip("/") + "/" + href
                if u not in found: found.append(u)
                if len(found) >= p["search"].get("maxCandidates", 3): return found
        return found

    def run_steps(self, p, vars_):
        vars_ = dict(vars_); cur = ""
        hdrs = p.get("headers", {})
        for n, st in enumerate(p["steps"], 1):
            op, frm = st["op"], st.get("from", "")
            inp = cur if frm in ("", "cur") else vars_.get(frm)
            if inp is None:
                self.say(f"  [{n}] {op}: değişken yok '{frm}' -> DURDU"); return None
            try:
                if op == "http_get":
                    url = expand(st["url"], vars_, True)
                    if url is None: self.say(f"  [{n}] http_get: URL'de boş değişken -> DURDU"); return None
                    ref = expand(st["referer"], vars_, False) if st.get("referer") else None
                    out = self.fetch(url, ref, hdrs)
                elif op == "regex":
                    fl = (re.S if st.get("dotAll") else 0) | (re.I if st.get("ignoreCase") else 0)
                    m = re.search(st["pattern"], inp, fl)
                    if not m: self.say(f"  [{n}] regex eşleşmedi: {st['pattern'][:70]} -> DURDU"); return None
                    out = m.group(st.get("group", 1))
                elif op == "json_path": out = json_path(inp, st["path"])
                elif op == "rot13": out = rot13(inp)
                elif op == "reverse": out = inp[::-1]
                elif op == "trim": out = inp.strip()
                elif op == "base64":
                    cs = "utf-8" if st.get("charset", "latin1").lower() in ("utf-8", "utf8") else "latin-1"
                    out = b64_lenient(inp, cs)
                elif op == "shift_key":
                    out = shift_key(inp, st["key"], st.get("mod", 5), st.get("add", 1), st.get("dir", "sub") != "add")
                elif op == "set": out = expand(st["value"], {**vars_, "cur": cur}, False)
                elif op == "check":
                    exp = vars_.get(st.get("expect", ""))
                    if exp and exp.isdigit():
                        m = re.search(st["pattern"], inp)
                        if m is None:
                            if st.get("required"): self.say(f"  [{n}] check: sayfada değer yok (required) -> DURDU"); return None
                            self.say(f"  [{n}] check: sayfada değer bulunamadı, atlandı")
                        else:
                            got = int(m.group(st.get("group", 1)))
                            if abs(got - int(exp)) > st.get("tolerance", 0):
                                self.say(f"  [{n}] check: sayfadaki {got} != beklenen {exp} (tolerans {st.get('tolerance', 0)}) -> YANLIŞ FİLM, DURDU"); return None
                            self.say(f"  [{n}] check: {got} ~ {exp} tamam")
                    else:
                        self.say(f"  [{n}] check: beklenen değer yok, atlandı")
                    out = cur
                else:
                    self.say(f"  [{n}] bilinmeyen işlem '{op}' (uygulama da reddeder) -> DURDU"); return None
            except Exception as e:
                self.say(f"  [{n}] {op} hata: {e} -> DURDU"); return None
            cur = out
            if st.get("as"): vars_[st["as"]] = out
            if op != "check":
                prev = out.replace("\n", " ")
                self.say(f"  [{n}] {op}: {prev[:90]}{'…' if len(prev) > 90 else ''}  ({len(out)} karakter)")
        res = ((vars_.get(p["result"]) if p.get("result") else cur) or "").strip()
        if not res.startswith(("http://", "https://")):
            self.say(f"  sonuç bir URL değil: {res[:80]!r}"); return None
        return res

    def find(self, p, req):
        queries = p.get("movie" if req["isMovie"] else "series", {}).get("queries", [])
        base_vars = {**request_vars(req), "base": p["base"]}
        tried = set()
        for rq in queries:
            q = expand(rq, base_vars, True)
            if q is None:
                self.say(f"sorgu atlandı (boş değişken): {rq}"); continue
            surl = expand(p["search"]["url"], {**base_vars, "q": urllib.parse.quote_plus(q)}, True)
            self.say(f"ARAMA: {q!r}  ->  {surl}")
            try: html = self.fetch(surl, p["base"] + "/", p.get("headers", {}))
            except Exception as e: self.say(f"  arama isteği başarısız: {e}"); continue
            cands = self.pick_candidates(html, p)
            self.say(f"  {len(cands)} aday: {cands}")
            for c in cands:
                if c in tried: continue
                tried.add(c)
                self.say(f"ADAY: {c}")
                hit = self.run_steps(p, {**base_vars, "page": c})
                if hit: return hit
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="dublaj_kaynaklari.json")
    ap.add_argument("--provider", required=True)
    ap.add_argument("--series", action="store_true")
    ap.add_argument("--imdb"); ap.add_argument("--title"); ap.add_argument("--year", type=int)
    ap.add_argument("--season", type=int); ap.add_argument("--episode", type=int)
    ap.add_argument("--duration", type=int, help="dakika (yanlış film kontrolü için)")
    ap.add_argument("--page", help="aramayı atla, bu sayfadan başla")
    ap.add_argument("--test-pick", metavar="HTML", help="kayıtlı arama sonucu HTML'inde pick regex'lerini dene")
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    prov = [p for p in cfg["providers"] if p["id"] == a.provider]
    if not prov: sys.exit("provider bulunamadı: " + a.provider)
    p = prov[0]
    r = Runner()
    if a.test_pick:
        html = open(a.test_pick, encoding="utf-8", errors="replace").read()
        for i, pat in enumerate(p["search"]["pick"], 1):
            hits = [m.group(1) for m in re.finditer(pat, html, re.S | re.I)]
            print(f"pick[{i}]: {len(hits)} eşleşme", hits[:5])
        print("seçilecek adaylar:", r.pick_candidates(html, p)); return
    req = dict(isMovie=not a.series, imdb=a.imdb, title=a.title, year=a.year,
               season=a.season, episode=a.episode, durationMin=a.duration)
    if a.page:
        res = r.run_steps(p, {**request_vars(req), "base": p["base"], "page": a.page})
    else:
        res = r.find(p, req)
    print("\nSONUÇ:", res or "BULUNAMADI")
    sys.exit(0 if res else 1)


if __name__ == "__main__":
    main()
