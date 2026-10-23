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

def main():
    recipe = json.load(open("dublaj_kaynaklari.json", encoding="utf-8"))
    assert recipe["schemaVersion"] == 1
    p = recipe["providers"][0]
    film_html = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else None
    expected = "https://s37.cdnimg4410.shop/mv/TEST-AUDIO-PLAYLIST"
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
        raise AssertionError("unexpected url " + url)
    R = Runner(fetch=http, verbose=False)
    vars_ = {"base": p["base"], "page": page, "durationMin": "145"}
    got = R.run_steps(p, vars_)
    print("pipeline result:", got)
    assert got == expected, got

    # 3) duration check rejects a wrong film
    assert R.run_steps(p, {**vars_, "durationMin": "95"}) is None
    print("duration mismatch rejected OK")
    # 4) series: no durationMin -> check skipped
    v = dict(vars_); v.pop("durationMin")
    assert R.run_steps(p, v) == expected
    print("check skipped without durationMin OK")

    # 5) real page: first steps up to the player URL
    if film_html:
        probe = dict(p); probe["steps"] = p["steps"][:6]; probe["result"] = "player"
        print("real page -> player url:", R.run_steps(probe, vars_))
    print("ALL OK")

main()
