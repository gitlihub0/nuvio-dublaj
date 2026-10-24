# Dublaj kaynakları rehberi

Bu rehber üç şeyi anlatır: uygulama sesi nasıl eşleştiriyor, dosyayı değiştirince ne zaman
yansıyor ve yeni bir site nasıl eklenir.

---

## 1. Ses nasıl eşleşiyor?

**IMDb kimliğine ve başlığa bakar. TMDB kimliği kullanılmıyor.**

Uygulama oynatılan içerikten şunları alır: IMDb kimliği (`tt...`), başlık, yıl, sezon/bölüm
ve (filmlerde) süre. Sonra tarifteki `queries` listesini **sırayla** dener:

| İçerik | Sorgu sırası (varsayılan tarif) |
|---|---|
| Film | 1) `{imdb}` &nbsp; 2) `{title}` |
| Dizi | `{title} {season} Sezon {episode} Bölüm` (IMDb ile aranmaz) |

Ayrıntılar:
- IMDb kimliği içerik kimliği `tt` ile başlıyorsa alınır (dizide `tt123:1:2` ise `tt123`).
  Nuvio bazı içerikleri `tmdb:12345` gibi bir kimlikle açar. O zaman IMDb kimliği **yoktur**
  ve arama sadece başlıkla yapılır. Bazı filmlerin bulunup bazılarının bulunmamasının en olası
  nedeni budur.
- Boş olan bir değişken içeren sorgu atlanır (örneğin filmde `{season}` yoktur).
- Her aramadan en fazla 3 aday sonuç (`maxCandidates`) denenir. Aday sayfada filmin süresi
  `check` adımıyla karşılaştırılır; fark 20 dakikadan büyükse aday reddedilir (yanlış film
  engeli). Dizilerde süre bilinmediği için bu kontrol atlanır.
- Sonuç bulunamazsa 10 dakika boyunca aynı içerik için tekrar aranmaz. Bulunursa 30 dakika
  hatırlanır. Tarif listesi yenilenince bu hafıza silinir.

**Bir film bulunmuyorsa olası nedenler** (en olasıdan başlayarak):
1. İçerik `tmdb:` kimliğiyle açıldı, başlık da sitedeki Türkçe adla uyuşmuyor
   (Nuvio "Spider-Man: Brand New Day" der, site "Örümcek Adam Yepyeni Bir Gün").
2. Sitede o filmin Türkçe dublajı yok ya da film hiç yok.
3. Site arama sonucu beklediğimiz HTML'e benzemiyor (`search.pick` regex'i eşleşmiyor).
4. Süre kontrolü yanlış filmi elemiş ya da doğru filmi (sitedeki süre farklı yazıyorsa) reddetmiş.
5. Sitenin şifre çözme yöntemi değişmiş (adımlardan biri durur).

Hangisi olduğunu görmek için bölüm 4'teki log komutunu kullan.

---

## 2. Dosyayı değiştirince uygulama ne zaman güncellenir?

Evet, otomatik güncellenir. APK gerekmez. Süreç:

| Durum | Ne olur |
|---|---|
| Ses menüsünde **Türkçe dublaj ara** | Her seferinde önce listeyi indirir, sonra arar. En hızlı yol. |
| Video açılınca otomatik arama | Telefondaki kopya **6 saatten eskiyse** yeniler, değilse eski kopyayı kullanır. |
| İnternet yok / GitHub'a ulaşılamıyor | Telefondaki son çalışan kopya kullanılır. |
| Yüklediğin JSON bozuk | Uygulama onu **yok sayar** ve eski çalışan kopyayı kullanmaya devam eder. Yani virgül hatası uygulamayı bozmaz ama değişiklik de uygulanmaz. |

Ek bilgiler:
- GitHub, `raw.githubusercontent.com` içeriğini yaklaşık 5 dakika önbelleğe alır. Commit'ten
  hemen sonra ilk deneme eski dosyayı getirebilir.
- Değişikliğin hemen denenmesini istiyorsan: commit et, 5 dakika bekle, uygulamada bir videoyu
  aç ve **Türkçe dublaj ara**'ya bas.
- Yüklemeden önce JSON'u doğrula: `python3 -c "import json;json.load(open('dublaj_kaynaklari.json',encoding='utf-8'))"`
  ve `python3 test_recipe.py`.
- Bu sistem CloudStream eklentilerinden bağımsızdır; eklenti güncellemesi gerekmez.

---

## 3. Yeni bir site nasıl eklenir?

Tarif, sitenin ses linkine ulaşma yolunu adım adım anlatan bir listedir. Önce yolu tarayıcıda
bulur, sonra JSON'a yazarsın.

### Adım 0. Gerekenler
- Bilgisayarında Python 3 (araçlar: `dubtool.py`, `test_recipe.py`).
- Tarayıcıda geliştirici araçları (F12).

### Adım 1. Aramayı bul
Sitenin arama kutusuna bir film yaz ve adres çubuğuna bak. Örnek:
`https://ornek.com/arama/inception` → `search.url` = `{base}/arama/{q}`.
Adres `?s=inception` biçimindeyse: `{base}/?s={q}`. IMDb kimliğiyle de arama yapıyorsa
`queries` listesinin başına `{imdb}` koy, yapmıyorsa koyma.

### Adım 2. Sonuç bağlantısını yakalayan regex'i yaz (`search.pick`)
Arama sonuç sayfasında sağ tık → **Sayfa kaynağını göster**, kaynağı `arama_sonucu.html`
olarak kaydet. İlk sonucun bağlantısına bak:

```html
<div class="item"><a href="/film/inception-izle/" title="Inception">...
```

Regex: **grup 1 bağlantıyı yakalamalı**: `<div class="item"><a href="([^"]+)"`

Daha dayanıklı, sadece yola bakan bir yedek de ekle: `href="((?:https://ornek\.com)?/film/[^"/]+/?)"`.
Regex'ler sırayla denenir; ilk eşleşenler önce gelir. Denemek için:

```
python3 dubtool.py --provider ornek --test-pick arama_sonucu.html
```

### Adım 3. Ses linkini bulduğun yolu çıkar
Bir film sayfasını aç, oynatmayı başlat ve **Network** sekmesinde `m3u8` ya da `mp3` ile filtrele.
Ses linkinin hangi isteğin cevabında geçtiğini bul. Genelde zincir şudur:

```
film sayfası  →  içinde bir player adresi (iframe/şifreli alan)  →  player sayfası  →  içinde ses linki
```

Her halkada şunları not et:
- **Veri nerede?** Sayfa kaynağında `m3u8`, `iframe`, `atob(`, `file:` gibi kelimeleri ara.
- **Düz mü, şifreli mi?** `http` ile başlıyorsa düz, rastgele harf yığınıysa kodlanmıştır.
  Kodlama büyük olasılıkla `base64`, `rot13`, `reverse` ve `shift_key` kombinasyonudur.
- **Hangi başlıklar gerekiyor?** İsteğe sağ tık → *Copy as cURL*, `-H 'referer: ...'` ve
  `origin` satırlarına bak. Ses linki yüklenirken gerekenleri `audioHeaders` içine yaz.

Ses linki **sadece ses** içermeli. Video da barındıran bir ana liste (master playlist) olursa
gereksiz video indirilir. Linki tarayıcıda açıp içindeki satırlara bak: `TYPE=AUDIO` ve görüntü
akışı yoksa uygundur.

### Adım 4. Adımları yaz (`steps`)

Kullanılabilir işlemler:

| op | parametreler | ne yapar |
|---|---|---|
| `http_get` | `url`, `referer`, `as` | sayfayı indirir |
| `regex` | `pattern` ya da `patterns` (liste, sırayla denenir, ilk eşleşen kazanır), `group` (1), `dotAll`, `ignoreCase` | metinden parça çeker |
| `json_path` | `path` (örn. `a.b[0].c`) | JSON'dan değer alır |
| `rot13` | | harf kaydırma |
| `reverse` | | tersine çevirir |
| `trim` | | baştaki/sondaki boşluğu siler |
| `base64` | `charset`: `latin1` (varsayılan) ya da `utf-8` | çözer (eksik dolgu ve `-_` tolere edilir) |
| `shift_key` | `key`, `mod` (5), `add` (1), `dir` (`sub`/`add`) | her karakteri `anahtar[i] % mod + add` kadar kaydırır |
| `hls_audio` | `lang` (tr), `name` | link görüntü içeren bir master liste ise ayrı **ses parçasının** adresini seçer; ses parçası yoksa durur (video asla eklenmez). Medya listesi ya da sadece-ses master olduğu gibi geçer |
| `replace` | `pattern`, `with`, `shift`, `ignoreCase` | desene uyan kısmı değiştirir. `with` içinde `\\1`, `\\2` grup başvurusu kullanılır. `shift`: `[{"group":2,"delta":1}]` o gruptaki harfi alfabede kaydırır |
| `require` | `pattern` | sonuç desene uymuyorsa adım durur (yanlış dil/kaynak elemesi) |
| `set` | `value` (`{cur}` önceki sonuç) | şablonla yeni metin üretir |
| `check` | `from`, `pattern`, `expect`, `tolerance`, `required` | sayfadaki sayıyı bilinenle karşılaştırır |

Kurallar:
- Her adım girdiyi `from` ile alır. Yazmazsan **önceki adımın sonucu** kullanılır.
- `as` ile sonuca isim verirsin; sonra `{isim}` ya da `from` ile kullanırsın.
- `{base}`, `{page}` (seçilen sonuç sayfası), `{imdb}`, `{title}`, `{year}`, `{season}`,
  `{episode}`, `{durationMin}`, `{q}` hazır gelir.
- `result` son ses linkinin değişken adıdır (`as` ile verdiğin isim).
- Regex'leri JSON içinde **çift ters bölü** ile yaz (`\\d`, `\\s`). `dubtool.py` aynı dosyayı
  okuduğu için hata yapınca hemen görürsün.
- En fazla 40 adım, yalnızca `https`.

### Adım 5. Sağlayıcıyı ekle
`providers` dizisine yeni bir nesne ekle. Alanların hepsi:

```json
{
  "id": "ornek",
  "enabled": true,
  "label": "Türkçe Dublaj",
  "lang": "tr",
  "base": "https://ornek.com",
  "audioHeaders": { "Origin": "{base}", "Referer": "{base}/" },
  "movie":  { "queries": ["{imdb}", "{title}"] },
  "series": { "queries": ["{title} {season}. Sezon {episode}. Bölüm"] },
  "search": {
    "url": "{base}/arama/{q}",
    "maxCandidates": 3,
    "pick": [ "<div class=\"item\"><a href=\"([^\"]+)\"" ]
  },
  "steps": [
    { "op": "http_get", "url": "{page}", "referer": "{base}/", "as": "html" },
    { "op": "regex", "from": "html", "pattern": "data-player=\"([^\"]+)\"", "group": 1 },
    { "op": "base64", "as": "playerUrl" },
    { "op": "http_get", "url": "{playerUrl}", "referer": "{base}/" },
    { "op": "regex", "pattern": "\"audio\"\\s*:\\s*\"([^\"]+)\"", "group": 1, "as": "audioUrl" }
  ],
  "result": "audioUrl"
}
```

(Bu yalnızca biçim örneğidir; adımlar senin sitenin yoluna göre değişir.)

Sağlayıcı sırası önemlidir: listede üstte olan önce denenir, ilk bulan kazanır.
Sağlayıcıyı geçici kapatmak için `"enabled": false` yaz.

### Adım 6. Bilgisayarda gerçek istekle dene (APK gerekmez)

```
# film
python3 dubtool.py --provider ornek --imdb tt1375666 --title "Inception" --duration 148

# dizi
python3 dubtool.py --provider ornek --series --title "Dizi Adı" --season 1 --episode 2

# aramayı atla, tek bir film sayfasından başla (adımları ayıklamak için)
python3 dubtool.py --provider ornek --page https://ornek.com/film/inception-izle/ --duration 148
```

Araç her adımın çıktısını gösterir ve nerede durduğunu yazar:

```
[3] regex eşleşmedi: data-player="([^"]+)" -> DURDU
```

Orada düzeltip tekrar çalıştır. Sonuç olarak bir `https://...` linki görürsen tarayıcıya
yapıştırıp ses çalıp çalmadığına bak; çalıyorsa tarif doğrudur.

### Adım 7. Yayınla ve telefonda dene
1. `python3 test_recipe.py` ile eski sağlayıcının bozulmadığını doğrula.
2. Dosyayı GitHub'a commit et, 5 dakika bekle.
3. Uygulamada bir film aç → ses menüsü → **Türkçe dublaj ara**.
4. Çalışmazsa bölüm 4'e bak.

---

## 4. Sorun giderme

Telefonu bilgisayara bağla ve logu izle:

```
adb logcat | grep -E "DubSource|DubPipeline|DubSearch|ExternalAudio|DubConfig"
```

| Log | Anlamı |
|---|---|
| `Config parse failed` / `Downloaded config is invalid` | JSON hatalı, eski kopya kullanılıyor |
| `Config schema N is newer` | Tarif, uygulamanın bilmediği bir sürümde; APK güncellemesi gerekir |
| `[id] search failed` | Arama isteği hata verdi (adres, ağ, siteyi engelleme) |
| `[id] trying <url>` | Aday bulundu, adımlar çalıştırılıyor |
| `[id] step 'regex' stopped: no match` | O adımın regex'i sayfaya uymuyor; site değişmiş olabilir |
| `step 'check' stopped` | Süre uyuşmadı (yanlış film ya da tolerans dar) |
| `[id] audio found` | Ses linki bulundu |
| `Dub found via ...` ve sonra ses gelmiyorsa | Link bulundu ama oynatılamıyor: `audioHeaders` (Referer/Origin) ya da link süresi dolmuş, yalnızca ses olmayan bir liste olabilir |

Sık durumlar:
- **Hiçbir şey bulunmuyor:** `dubtool.py --page <bir film sayfası>` ile adımları dene.
- **Arama sonucu yok:** `--test-pick` ile `search.pick` regex'ini kayıtlı HTML'de dene.
- **Doğru film reddediliyor:** `check` adımının `tolerance` değerini artır ya da `pattern`'ı
  sitenin süre biçimine göre düzelt.
- **Yanlış film geliyor:** `tolerance` değerini düşür, `{title}` sorgusunu kaldır, yalnızca
  `{imdb}` kullan.

---

## 5. Sınırlar

- Tarif yalnızca yukarıdaki işlemleri kullanabilir. Site tamamen yeni bir şifreleme (örneğin
  AES) kullanıyorsa uygulamaya yeni bir `op` eklemek ve APK'yı yenilemek gerekir.
- Sadece ExoPlayer ile çalışır. mpv motorunda dublaj eklenmez.
- TMDB kimliği ve içeriğin orijinal adı şu an tarife verilmiyor. Bunlar eklenirse `tmdb:`
  kimlikli içeriklerde eşleşme artar; bu bir uygulama güncellemesi gerektirir.
- Uzaktan sadece **veri** gelir, kod çalıştırılmaz. Yine de depoyu sadece sen düzenleyebilmelisin
  (GitHub hesabında iki adımlı doğrulama aç).


## 6. Link video çıkıyorsa

`dubtool.py` çıktısının sonunda **LİSTE İNCELEMESİ** bölümü çıkar: link ses mi, görüntü içeren
master liste mi söyler. Tarifin son adımı `hls_audio` olmalı (varsayılan tarifte var). Sorun
sürüyorsa decoded içeriği görmek için:

```
python3 dubtool.py --provider fullhdfilmizlesene --imdb tt... --title "..." --duration 120 --dump
python3 dubtool.py --provider fullhdfilmizlesene --inspect "https://...ses-linki"
```

## 7. Ses linkinin içinden okunanlar (gerçek örnekler)

Linkin gövdesi `rot13` + `base64` ile çözülünce yayın adını verir:
`Spider-Man.Brand.New.Day.2026.WEB-DL.1080p.DUAL.x264-HDM`. **DUAL**, yayında iki ses olduğu
(Türkçe + İngilizce) anlamına gelir. Linkin sonundaki `vr1b1080l0tra1` parçasında `tr` dil
kodu gibi görünür; İngilizce için farklı bir son ek beklenir (doğrulanmadı).
Tarifteki `require` adımı `tr` ile bitmeyen linki reddeder, uygulama da parçanın dili
`und` dışında bir şeyse ve Türkçe değilse sesi eklemez.

Parçaların `.jpg` uzantılı olması normaldir (site gizliyor). `dubtool.py --inspect <link>`
ilk parçayı indirip içinde video olup olmadığını ve dilini söyler.

### Dil son eki ve klasör harfi (fullhdfilmizlesene)

Aynı filmin üç linki yalnızca sondaki ek ve klasör harfiyle ayrılır (gerçek örnek, sunucu s28):

| Tür | Klasör | Son ek |
|---|---|---|
| Türkçe ses | `/mx/` | `...vr1b1080l0tra1` |
| İngilizce ses | `/mw/` | `...vr1b1080l0ena2` |
| Video | `/ms/` | `...avr1` |

Tarif `cm` hangisini verirse versin Türkçe linke çevirir: `ena2` için klasör harfi +1 ve son ek
`tra1`; video için harf +5 ve son ek `vr1b1080l0tra1`. Üretilen link yoksa (404) kaynak reddedilir.
**Uyarı:** +1 ve +5 farkı yalnızca s28 sunucusunda doğrulandı. Başka sunucuda (örneğin Türkçe
klasör `/mv/` olan s37) çalışmazsa `shift` değerlerini o sunucunun üç linkine göre düzelt.

## 8. Hedef kural ve ilk çözme adımı

Hedef her zaman `tra1` ile biten link. Tarif önce decoded içinde `tra\d+` ile biten bir link arar
(varsa doğrudan onu alır), bulamazsa `cm` değerine düşer; `cm` İngilizce ya da video ise bu
linki Türkçeye çevirmeyi dener (404 ise reddeder). `dubtool.py` uzun çıktıların **son 28
karakterini** de gösterir, böylece linkin `tra1` / `ena2` / `avr1` ile bittiği görünür.
Sorun olursa `--dump` ile decoded içeriğin tamamını al.
