"""Offline check of dublaj_kaynaklari.json.

Mirrors the app's DubPipelineRunner/DubOps step semantics, then runs the recipe against:
  - a synthetic search page,
  - a real saved film page (pass its path as argv[1]) for the scx step,
  - a synthetic player page built by encoding a known URL with the same scheme the site uses.
Usage: python3 test_recipe.py [film_page.html]
"""
import base64, json, re, sys
from dubtool import Runner, rot13, expand

def encode_p8(payload):
    s = base64.b64encode(payload.encode()).decode()
    shifted = bytes((ord(ch) + (ord("K9L"[i % 3]) % 5 + 1)) & 0xFF for i, ch in enumerate(s))
    return base64.b64encode(shifted).decode()[::-1]

# Çok dilli master liste: video akışı + ayrı İngilizce/Türkçe ses parçaları
MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="English",LANGUAGE="en",URI="en/a.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Turkce",LANGUAGE="tr",URI="tr/a.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=1920x1080,AUDIO="a"
v/v.m3u8
"""

def main():
    recipe = json.load(open("dublaj_kaynaklari.json", encoding="utf-8"))
    assert recipe["schemaVersion"] == 1
    p = recipe["providers"][0]
    film_html = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else None
    expected = "https://s37.cdnimg4410.shop/mv/TEST-AUDIO-PLAYLISTvr1b1080l0tra1"
    final = "https://s37.cdnimg4410.shop/mv/tr/a.m3u8"
    player_url = "https://rapidvid.org/vx/v1x348972af"
    page = p["base"] + "/film/orumcek-adam-yepyeni-bir-gun-spider-man-brand-new-day/"
    search_html = f'<ul><li class="film other"><a href="/film/orumcek-adam-yepyeni-bir-gun-spider-man-brand-new-day/"><img></a></li></ul>'

    # 1) search pick regexes
    found = []
    for pat in p["search"]["pick"]:
        found += [m.group(1) for m in re.finditer(pat, search_html, re.S | re.I)]
    assert found and found[0].endswith("brand-new-day/"), found
    print("search pick OK:", found[0])

    # 2) full pipeline
    def http(url, referer=None, headers=None):
        if url == page:
            return film_html if film_html else '"duration": "PT145M"; var scx = {"atom":{"sx":{"t":["%s"]}}};' % rot13(base64.b64encode(player_url.encode()).decode())
        if url == player_url:
            return "var _p8 = '%s';" % encode_p8('{"title":"x","cm":"%s","z":1}' % expected)
        if url == expected:
            return MASTER
        raise AssertionError("unexpected url " + url)
    R = Runner(fetch=http, verbose=False)
    vars_ = {"base": p["base"], "page": page, "durationMin": "145"}
    got = R.run_steps(p, vars_)
    print("pipeline result:", got)
    assert got == final, got

    # 2b) Gerçek sunucu (s28) örneği: ena2 ve video linkinden Türkçe link üretilir
    TR = "https://s28.cdnimg1399.shop/mx/FJ5wMKO0xi28vr1b1080l0tra1"
    EN = "https://s28.cdnimg1399.shop/mw/FJ5wMKO0xi28vr1b1080l0ena2"
    VID = "https://s28.cdnimg1399.shop/ms/FJ5wMKO0xi28avr1"
    for src in (EN, VID, TR):
        pl = encode_p8('{"cm":"%s"}' % src)
        def http_x(url, referer=None, headers=None, pl=pl):
            if url == player_url: return "var _p8 = '%s';" % pl
            if url == TR: return MASTER
            if url in (EN, VID): raise AssertionError("must not fetch " + url)
            return http(url, referer, headers)
        assert Runner(fetch=http_x, verbose=False).run_steps(p, vars_) == "https://s28.cdnimg1399.shop/mx/tr/a.m3u8", src
    print("ena2 / video -> tra1 (folder shifted) OK")
    # 2b2) decoded içinde hem İngilizce hem Türkçe link varsa Türkçe olan seçilir (doğrudan, tahmin yok)
    both = encode_p8('{"cm":"%s","x":"%s"}' % (EN, TR))
    def http_both(url, referer=None, headers=None):
        if url == player_url: return "var _p8 = '%s';" % both
        if url == TR: return MASTER
        if url == EN: raise AssertionError("must not fetch " + url)
        return http(url, referer, headers)
    assert Runner(fetch=http_both, verbose=False).run_steps(p, vars_) == "https://s28.cdnimg1399.shop/mx/tr/a.m3u8"
    print("Turkish url picked directly from decoded OK")
    # 2c) tra1 yoksa (404) kaynak reddedilir, İngilizce asla verilmez
    en = encode_p8('{"cm":"%s"}' % EN)
    def http_404(url, referer=None, headers=None):
        if url == player_url: return "var _p8 = '%s';" % en
        raise IOError("404")
    assert Runner(fetch=http_404, verbose=False).run_steps(p, vars_) is None
    print("missing tra1 rejected OK")

    # 3) duration check rejects a wrong film
    assert R.run_steps(p, {**vars_, "durationMin": "95"}) is None
    print("duration mismatch rejected OK")
    # 4) series: no durationMin -> check skipped
    v = dict(vars_); v.pop("durationMin")
    assert R.run_steps(p, v) == final
    print("check skipped without durationMin OK")

    # 5) real page: first steps up to the player URL
    if film_html:
        probe = dict(p); probe["steps"] = p["steps"][:6]; probe["result"] = "player"
        print("real page -> player url:", R.run_steps(probe, vars_))
    print("ALL OK")

main()
