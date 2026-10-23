# nuvio-dublaj

NuvioTV için Türkçe dublaj kaynak tarifleri. Uygulama bu depodaki `dublaj_kaynaklari.json`
dosyasını indirir; site değişince burayı düzeltmek yeter, APK'yı yeniden kurmak gerekmez.

Adres (uygulama içinde sabit):
`https://raw.githubusercontent.com/gitlihub0/nuvio-dublaj/main/dublaj_kaynaklari.json`

## Ne zaman güncellenir?
- Otomatik: video hazır olunca dublaj aranır, kaynak listesi 6 saatten eskiyse yenilenir.
- Elle: ses menüsünde **Türkçe dublaj ara** her zaman önce güncel listeyi indirir.
- İnternet yoksa ya da dosya bozuksa telefondaki son çalışan kopya kullanılır.

## Dosya yapısı
```
schemaVersion   1 (uygulama daha yenisini görürse listeyi yok sayar, APK güncellemesi gerekir)
autoSearch      false yaparsan otomatik arama kapanır, menüdeki buton çalışmaya devam eder
providers[]     sırayla denenir, ilk bulan kazanır
  id, label, lang, enabled
  base          https ile başlamalı
  audioHeaders  ses akışı yüklenirken gönderilir ({base} kullanılabilir)
  movie.queries / series.queries   arama kelimeleri
  search.url    {base}/arama/{q}
  search.pick   sonuç sayfasından bağlantı çeken regex'ler (grup 1 = href)
  steps[]       aşağıdaki işlemler
  result        son URL'nin değişken adı
```

Kullanılabilir değişkenler: `{base} {imdb} {title} {title_raw} {year} {season} {episode}
{durationMin} {q} {page}` ve `as` ile adlandırdığın her şey. Boş olan bir değişken
sorgu/URL içinde geçiyorsa o satır atlanır (örneğin filmde `{season}` yoktur).

## İşlemler (`steps`)
| op | ne yapar |
|---|---|
| `http_get` | `url`, `referer` ile sayfayı indirir |
| `regex` | `pattern`, `group`, `dotAll`, `ignoreCase` |
| `json_path` | `path`, örn. `atom.sx.t[0]` |
| `rot13`, `reverse`, `trim` | metin dönüşümü |
| `base64` | çözer. `charset`: `latin1` (varsayılan) veya `utf-8` |
| `shift_key` | `key`, `mod`, `add`, `dir` (`sub`/`add`) bayt kaydırma |
| `set` | `value` şablonu, `{cur}` önceki sonuç |
| `check` | sayfadaki sayıyı bilinen değerle karşılaştırır (`pattern`, `expect`, `tolerance`) |

Her adım `from` ile bir değişkeni okur (yoksa önceki sonucu), `as` ile sonucu adlandırır.
Bu listede olmayan yeni bir şifre çözme yöntemi için uygulamaya yeni `op` eklemek gerekir.

## Sık bozulanlar ve çözümü
- **Domain değişti:** `base` ve `pick` içindeki domain.
- **Arama sonucu bulunamıyor:** `search.pick` regex'ini sonuç sayfasının HTML'ine göre düzelt.
- **Ses gelmiyor:** `scx`, `_p8`, `K9L` adımlarındaki regex ve anahtarı kontrol et.
- **Yanlış film geliyor:** `check` adımının `tolerance` değerini düşür.

## Test
```
python3 test_recipe.py film_sayfasi.html
```
Tarifi uygulamadaki işlem mantığıyla çalıştırır (sahte arama ve oynatıcı sayfasıyla) ve
kayıtlı bir film sayfasında `scx` adımının oynatıcı adresine ulaştığını doğrular.
