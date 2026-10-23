"""Offline check of dublaj_kaynaklari.json.

Mirrors the app's DubPipelineRunner/DubOps step semantics, then runs the recipe against:
  - a synthetic search page,
  - a real saved film page (pass its path as argv[1]) for the scx step,
  - a synthetic player page built by encoding a known URL with the same scheme the site uses.
Usage: python3 test_recipe.py [film_page.html]
"""
import base64, codecs, json, re, sys, urllib.parse

def rot13(s): return codecs.decode(s, "rot13")

def b64_lenient(s, charset):
    out = []
    for c in s:
        if c.isascii() and (c.isalnum() or c in "+/"): out.append(c)
        elif c == "-": out.append("+")
        elif c == "_": out.append("/")
    if len(out) % 4 == 1: out.pop()
    while len(out) % 4: out.append("=")
    return base64.b64decode("".join(out)).decode(charset)

def shift_key(s, key, mod, add, sub):
    r = []
    for i, ch in enumerate(s):
        v = ord(ch) & 0xFF
        off = ord(key[i % len(key)]) % mod + add
        r.append(chr((v - off if sub else v + off) & 0x10FFFF if (v - off if sub else v + off) >= 0 else 0xFFFF))
    return "".join(r)

def json_path(text, path):
    node = json.loads(text)
    for key, idx in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path):
        if key: node = node[key]
        else: node = node[int(idx)]
    return node if isinstance(node, str) else json.dumps(node)

def expand(t, vars_, strict):
    miss = [False]
    def sub(m):
        v = vars_.get(m.group(1))
        if not v: miss[0] = True; return ""
        return v
    r = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, t)
    return None if strict and miss[0] else r

def run_steps(provider, vars_, http):
    vars_ = dict(vars_); cur = ""
    for st in provider["steps"]:
        frm = st.get("from", "")
        inp = cur if frm in ("", "cur") else vars_[frm]
        op = st["op"]
        if op == "http_get":
            url = expand(st["url"], vars_, True); out = http(url)
        elif op == "regex":
            fl = (re.S if st.get("dotAll") else 0) | (re.I if st.get("ignoreCase") else 0)
            m = re.search(st["pattern"], inp, fl)
            if not m: return None
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
                    if st.get("required"): return None
                elif abs(int(m.group(st.get("group", 1))) - int(exp)) > st.get("tolerance", 0): return None
            out = cur
        else: raise SystemExit("unknown op " + op)
        cur = out
        if st.get("as"): vars_[st["as"]] = out
    res = (vars_.get(provider["result"]) if provider.get("result") else cur) or ""
    return res.strip() if res.startswith("http") else None

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
    def http(url):
        if url == page:
            return film_html if film_html else '"duration": "PT145M"; var scx = {"atom":{"sx":{"t":["%s"]}}};' % rot13(base64.b64encode(player_url.encode()).decode())
        if url == player_url:
            return "var _p8 = '%s';" % encode_p8('{"title":"x","cm":"%s","z":1}' % expected)
        raise AssertionError("unexpected url " + url)
    vars_ = {"base": p["base"], "page": page, "durationMin": "145"}
    got = run_steps(p, vars_, http)
    print("pipeline result:", got)
    assert got == expected, got

    # 3) duration check rejects a wrong film
    assert run_steps(p, {**vars_, "durationMin": "95"}, http) is None
    print("duration mismatch rejected OK")
    # 4) series: no durationMin -> check skipped
    v = dict(vars_); v.pop("durationMin")
    assert run_steps(p, v, http) == expected
    print("check skipped without durationMin OK")

    # 5) real page: first steps up to the player URL
    if film_html:
        probe = dict(p); probe["steps"] = p["steps"][:6]; probe["result"] = "player"
        print("real page -> player url:", run_steps(probe, vars_, http))
    print("ALL OK")

main()
