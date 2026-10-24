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


def parse_attrs(line):
    return {k.upper(): v.strip('"') for k, v in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line)}


def hls_audio(text, base_url, lang, name):
    """Master liste ise ayrı SES parçasının adresini döndürür. (DubOps.kt ile aynı mantık)
    Dönüş: (url, not). Medya listesi ise adresi olduğu gibi bırakır (None döner)."""
    if "#EXT-X-STREAM-INF" not in text:
        return None, "medya listesi (master değil), olduğu gibi kullanılır"
    infs = [parse_attrs(l) for l in text.splitlines() if l.startswith("#EXT-X-STREAM-INF")]
    if not any("RESOLUTION" in a or re.search(r"avc|hvc|hev|vp0?9|av01", a.get("CODECS", ""), re.I) for a in infs):
        return None, "master ama görüntü akışı yok (sadece ses), olduğu gibi kullanılır"
    media = []
    for ln in text.splitlines():
        if ln.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in ln.upper():
            a = parse_attrs(ln)
            if a.get("URI"): media.append(a)
    if not media:
        raise ValueError("master liste ama ayrı ses parçası yok (ses videonun içinde)")
    lang, name = (lang or "").lower(), (name or "").lower()

    def ok(a):
        l = a.get("LANGUAGE", "").lower(); n = a.get("NAME", "").lower()
        if name and name not in n: return False
        if not lang: return True
        return l.startswith(lang) or lang in n or (lang == "tr" and ("türk" in n or "turk" in n or l.startswith("tur")))
    pick = [a for a in media if ok(a)]
    if not pick:
        raise ValueError("istenen dilde ses parçası yok; var olanlar: " +
                         ", ".join(f"{a.get('LANGUAGE','?')}/{a.get('NAME','?')}" for a in media))
    return urllib.parse.urljoin(base_url, pick[0]["URI"]), "seçildi: %s/%s" % (pick[0].get("LANGUAGE", "?"), pick[0].get("NAME", "?"))


def inspect_playlist(text, base_url="", fetch_bytes=None):
    """Bir m3u8 içeriğinin ses mi video mu olduğunu özetler."""
    lines = text.splitlines()
    out = []
    if "#EXT-X-STREAM-INF" in text:
        n = sum(1 for l in lines if l.startswith("#EXT-X-STREAM-INF"))
        out.append(f"MASTER liste: {n} görüntü akışı (video var!)")
        for l in lines:
            if l.startswith("#EXT-X-MEDIA") and "TYPE=AUDIO" in l.upper():
                a = parse_attrs(l); out.append(f"  ses parçası: dil={a.get('LANGUAGE','?')} ad={a.get('NAME','?')} uri={'var' if a.get('URI') else 'yok'}")
    elif "#EXTINF" in text:
        segs = [l for l in lines if l and not l.startswith("#")]
        out.append(f"MEDYA listesi: {len(segs)} parça, ilk: {segs[0][:70] if segs else '-'}")
        if any(l.startswith("#EXT-X-MAP") for l in lines): out.append("  EXT-X-MAP var (fMP4)")
        total = sum(float(m) for m in re.findall(r"#EXTINF:([\d.]+)", text))
        out.append(f"  toplam süre: {total/60:.1f} dk")
        if "#EXT-X-KEY" in text: out.append("  UYARI: şifreli (EXT-X-KEY)")
        if fetch_bytes and segs:
            seg = urllib.parse.urljoin(base_url, segs[0])
            try:
                streams = sniff_segment(fetch_bytes(seg))
                kinds = {k for k, _, _ in streams}
                for k, c, l in streams: out.append(f"  parça içeriği: {k} {c} dil={l or '?'}")
                if "video" in kinds: out.append("  >>> VİDEO İÇERİYOR: bu link izole ses DEĞİL")
                elif "audio" in kinds: out.append("  >>> sadece SES: uygun")
            except Exception as e:
                out.append(f"  ilk parça incelenemedi: {e}")
    else:
        out.append("m3u8 gibi görünmüyor: " + text[:80].replace("\n", " "))
    return out


def live_fetch_bytes(url, referer, headers, limit=2 * 1024 * 1024):
    if not url.startswith("https://"):
        raise ValueError("sadece https desteklenir: " + url)
    h = {"User-Agent": UA, **headers}
    if referer: h["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
        return r.read(limit)


TS_TYPES = {0x01: ("video", "MPEG-1"), 0x02: ("video", "MPEG-2"), 0x1B: ("video", "H.264"), 0x24: ("video", "HEVC"),
            0x03: ("audio", "MP3"), 0x04: ("audio", "MP3"), 0x0F: ("audio", "AAC"), 0x11: ("audio", "AAC-LATM"),
            0x81: ("audio", "AC3"), 0x87: ("audio", "E-AC3"), 0x06: ("audio?", "private (AC3/DTS/altyazı olabilir)")}


def sniff_segment(data):
    """Bir HLS parçasının (.ts ya da fMP4) içindeki akışları listeler.
    Dönüş: [(tür, codec, dil)]; tür 'video' ya da 'audio'. Başında sahte resim başlığı olsa da çalışır."""
    out = []
    # --- MPEG-TS: 188 baytlık paketler, 0x47 eşitleme baytı
    start = next((i for i in range(0, min(len(data) - 564, 4096)) if data[i] == 0x47 and data[i + 188] == 0x47 and data[i + 376] == 0x47), None)
    if start is not None:
        sections, pmt_pids = {}, set()
        for p in range(start, len(data) - 187, 188):
            pk = data[p:p + 188]
            if pk[0] != 0x47: break
            pid = ((pk[1] & 0x1F) << 8) | pk[2]
            pusi = pk[1] & 0x40
            af = (pk[3] >> 4) & 3
            off = 4 + (pk[4] + 1 if af in (2, 3) else 0)
            if af == 2: continue
            if pid == 0 or pid in pmt_pids:
                payload = pk[off:]
                if pusi: sections[pid] = bytearray(payload[1 + payload[0]:])
                elif pid in sections: sections[pid] += payload
                sec = sections.get(pid)
                if not sec or len(sec) < 3: continue
                ln = ((sec[1] & 0x0F) << 8) | sec[2]
                if len(sec) < 3 + ln: continue
                if pid == 0 and sec[0] == 0:
                    for i in range(8, 3 + ln - 4, 4):
                        prog = (sec[i] << 8) | sec[i + 1]
                        if prog: pmt_pids.add(((sec[i + 2] & 0x1F) << 8) | sec[i + 3])
                    sections.pop(0, None)
                elif sec[0] == 2:
                    pil = ((sec[10] & 0x0F) << 8) | sec[11]
                    i = 12 + pil
                    end = 3 + ln - 4
                    while i + 5 <= end:
                        st = sec[i]; il = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
                        lang, j = "", i + 5
                        while j + 2 <= i + 5 + il:
                            tag, dl = sec[j], sec[j + 1]
                            if tag == 0x0A and dl >= 3: lang = bytes(sec[j + 2:j + 5]).decode("latin-1")
                            j += 2 + dl
                        kind, codec = TS_TYPES.get(st, ("?", "tür 0x%02X" % st))
                        out.append((kind, codec, lang))
                        i += 5 + il
                    return out
        return out or [("?", "MPEG-TS (PMT okunamadı)", "")]
    # --- fMP4: hdlr kutusu video/ses söyler, mdhd dili
    i = 0
    while True:
        h = data.find(b"hdlr", i)
        if h < 0: break
        handler = data[h + 12:h + 16]
        kind = {b"vide": "video", b"soun": "audio"}.get(handler, handler.decode("latin-1", "replace"))
        lang = ""
        m = data.rfind(b"mdhd", 0, h)
        if m >= 0:
            v = data[m + 4]
            o = m + 4 + (24 if v == 0 else 32)
            if o + 2 <= len(data):
                x = (data[o] << 8) | data[o + 1]
                lang = "".join(chr(((x >> s) & 31) + 0x60) for s in (10, 5, 0))
        out.append((kind, "fMP4", lang)); i = h + 4
    return out


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
    def __init__(self, fetch=live_fetch, verbose=True, dump=False):
        self.fetch, self.verbose, self.dump = fetch, verbose, dump

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
                    pats = st.get("patterns") or [st["pattern"]]
                    out = None
                    for pt in pats:
                        m = re.search(pt, inp, fl)
                        if m:
                            out = m.group(st.get("group", 1)); break
                    if out is None:
                        self.say(f"  [{n}] regex eşleşmedi: {pats[0][:70]} -> DURDU"); return None
                elif op == "json_path": out = json_path(inp, st["path"])
                elif op == "rot13": out = rot13(inp)
                elif op == "reverse": out = inp[::-1]
                elif op == "trim": out = inp.strip()
                elif op == "base64":
                    cs = "utf-8" if st.get("charset", "latin1").lower() in ("utf-8", "utf8") else "latin-1"
                    out = b64_lenient(inp, cs)
                elif op == "shift_key":
                    out = shift_key(inp, st["key"], st.get("mod", 5), st.get("add", 1), st.get("dir", "sub") != "add")
                elif op == "hls_audio":
                    ah = {k: expand(v, vars_, False) for k, v in p.get("audioHeaders", {}).items()}
                    pl = self.fetch(inp.strip().split("#")[0], ah.get("Referer"), {**ah})
                    u, note = hls_audio(pl, inp.strip().split("#")[0], st.get("lang", "tr"), st.get("name"))
                    self.say(f"  [{n}] hls_audio: {note}")
                    out = u or inp.strip()
                elif op == "replace":
                    fl = re.I if st.get("ignoreCase") else 0
                    shifts = {int(x["group"]): int(x["delta"]) for x in st.get("shift", [])}
                    def sub_(m):
                        def g(k):
                            v = m.group(k) or ""
                            if k in shifts and len(v) == 1 and v.isalpha():
                                base = ord("a") if v.islower() else ord("A")
                                v = chr((ord(v) - base + shifts[k]) % 26 + base)
                            return v
                        return re.sub(r"\\(\d)", lambda x: g(int(x.group(1))), st.get("with", ""))
                    out = re.sub(st["pattern"], sub_, inp.strip(), flags=fl)
                    if out != inp.strip(): self.say(f"  [{n}] replace: ...{inp.strip()[-18:]} -> ...{out[-18:]}")
                elif op == "require":
                    if not re.search(st["pattern"], inp.strip().split("#")[0]):
                        self.say(f"  [{n}] require: '{st['pattern']}' uymuyor -> bu kaynak istenen dilde değil, DURDU"); return None
                    out = inp
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
                lim = 100000 if self.dump else 90
                tail = f" ... SON: {prev[-28:]}" if len(prev) > lim else ""
                self.say(f"  [{n}] {op}: {prev[:lim]}{'…' if len(prev) > lim else ''}{tail}  ({len(out)} karakter)")
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
    ap.add_argument("--dump", action="store_true", help="her adımın tam çıktısını göster (decoded içeriği görmek için)")
    ap.add_argument("--inspect", metavar="URL", help="bir ses/video listesini indir, ses mi video mu söyle")
    ap.add_argument("--referer", default=None, help="--inspect için Referer (Origin otomatik)")
    ap.add_argument("--test-pick", metavar="HTML", help="kayıtlı arama sonucu HTML'inde pick regex'lerini dene")
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    prov = [p for p in cfg["providers"] if p["id"] == a.provider]
    if not prov: sys.exit("provider bulunamadı: " + a.provider)
    p = prov[0]
    r = Runner(dump=a.dump)
    if a.inspect:
        h = {}
        ref = a.referer or p["base"] + "/"
        h["Origin"] = urllib.parse.urlparse(ref).scheme + "://" + urllib.parse.urlparse(ref).netloc
        text = live_fetch(a.inspect.split("#")[0], ref, h)
        print("\n".join(inspect_playlist(text, a.inspect.split("#")[0], lambda u: live_fetch_bytes(u, ref, h)))); print("--- ilk 1500 karakter ---"); print(text[:1500]); return
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
    if res:
        try:
            ah = {k: expand(v, {"base": p["base"]}, False) for k, v in p.get("audioHeaders", {}).items()}
            print("\nLİSTE İNCELEMESİ (ses mi video mu):")
            print("\n".join("  " + x for x in inspect_playlist(live_fetch(res.split("#")[0], ah.get("Referer"), ah), res.split("#")[0], lambda u: live_fetch_bytes(u, ah.get("Referer"), ah))))
        except Exception as e:
            print("  liste indirilemedi:", e)
    sys.exit(0 if res else 1)


if __name__ == "__main__":
    main()
