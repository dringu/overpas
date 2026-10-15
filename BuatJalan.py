#!/usr/bin/env python3
"""
Membuat GeoJSON seluruh jalan di Kecamatan Krejengan dari data OpenStreetMap,
dipotong sesuai batas kecamatan dan diberi atribut desa.

Pemakaian:
  A) Unduh langsung dari Overpass (perlu internet):
       python buat_jalan_krejengan.py --folder ./data
  B) Pakai hasil ekspor overpass-turbo (export.geojson):
       python buat_jalan_krejengan.py --folder ./data --osm export.geojson

--folder berisi: batas_krejengan.geojson dan 35_13_15_2001..2017.geojson
Keluaran: jalan_krejengan.geojson (+ ringkasan di layar)
Dependensi: pip install shapely pyproj requests
"""
import argparse, glob, json, os, sys
from shapely.geometry import shape, mapping
from shapely.ops import transform
from shapely.strtree import STRtree
from pyproj import Transformer

HIGHWAY_JALAN = {"motorway","trunk","primary","secondary","tertiary","unclassified",
                 "residential","service","track","living_street","road",
                 "motorway_link","trunk_link","primary_link","secondary_link","tertiary_link"}

def baca_geom(path):
    d = json.load(open(path))
    if d["type"] == "FeatureCollection": d = d["features"][0]
    return d["properties"], shape(d["geometry"])

def overpass_query(bbox):
    s, w, n, e = bbox
    return f"""[out:json][timeout:120];
(way["highway"]({s},{w},{n},{e}););
out geom;"""

MIRROR = ["https://overpass.private.coffee/api/interpreter",
          "https://overpass.kumi.systems/api/interpreter",
          "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
          "https://overpass-api.de/api/interpreter"]

def _unduh_satu(bbox, percobaan=3):
    import requests, time
    for ulang in range(percobaan):
        for url in MIRROR:
            try:
                r = requests.post(url, data={"data": overpass_query(bbox)}, timeout=180,
                                  headers={"User-Agent": "krejengan-jalan/1.0"})
                r.raise_for_status(); data = r.json()
                els = data.get("elements", [])
                if data.get("remark") and not els:
                    raise RuntimeError("remark: " + data["remark"])
                if not els:
                    raise RuntimeError("elemen kosong")
                print(f"ok: {url} -> {len(els)} elemen", file=sys.stderr)
                return els
            except Exception as ex:
                print("gagal", url, str(ex)[:80], file=sys.stderr)
        time.sleep(15 * (ulang + 1))
    sys.exit("Semua server Overpass sibuk. Coba lagi beberapa menit lagi.")

def unduh_overpass(bbox, n=2):
    """Bagi bbox jadi n x n petak, unduh satu per satu, gabungkan tanpa duplikat."""
    s, w, nn, e = bbox
    ds, dw = (nn - s) / n, (e - w) / n
    unik = {}
    for i in range(n):
        for j in range(n):
            petak = (s + i*ds, w + j*dw, s + (i+1)*ds, w + (j+1)*dw)
            for el in _unduh_satu(petak):
                unik[el["id"]] = el
    fitur = []
    for el in unik.values():
        if el["type"] != "way" or "geometry" not in el: continue
        coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
        fitur.append({"type":"Feature","properties":{"id":el["id"],**el.get("tags",{})},
                      "geometry":{"type":"LineString","coordinates":coords}})
    return fitur

def muat_osm(path):
    d = json.load(open(path))
    if "features" in d:
        return d["features"]
    fitur = []
    for el in d.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el: continue
        fitur.append({"type":"Feature","properties":{"id":el["id"],**el.get("tags",{})},
                      "geometry":{"type":"LineString","coordinates":[[p["lon"],p["lat"]] for p in el["geometry"]]}})
    return fitur

def cari_osm(folder):
    for nama in ("osm_krejengan_cache.geojson","export.geojson","export.json","overpass.json","overpass.geojson"):
        for dasar in (folder, os.getcwd()):
            p = os.path.join(dasar, nama)
            if os.path.exists(p): return p
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--osm")
    ap.add_argument("--out", default="jalan_krejengan.geojson")
    ap.add_argument("--semua", action="store_true", help="sertakan juga footway/path/dll")
    a = ap.parse_args()

    _, kec = baca_geom(os.path.join(a.folder, "batas_krejengan.geojson"))
    berkas = sorted(glob.glob(os.path.join(a.folder, "35?13?15?20*.geojson"))) or \
             sorted(glob.glob(os.path.join(a.folder, "**", "35?13?15?20*.geojson"), recursive=True))
    desa = [baca_geom(f) for f in berkas]
    desa = [(p.get("name"), p.get("code"), g) for p, g in desa]

    if not desa:
        print("File desa tidak ditemukan di:", os.path.abspath(a.folder), file=sys.stderr)
        print("Isi folder:", sorted(os.listdir(a.folder))[:30], file=sys.stderr)
        sys.exit("Pastikan --folder menunjuk ke folder berisi 35_13_15_2001..2017.geojson")

    CACHE = os.path.join(a.folder, "osm_krejengan_cache.geojson")
    sumber = a.osm or cari_osm(a.folder)
    if sumber:
        print("memakai data OSM yang sudah ada:", sumber, "(tanpa unduh)", file=sys.stderr)
        fitur = muat_osm(sumber)
    else:
        minx, miny, maxx, maxy = kec.bounds
        fitur = unduh_overpass((miny-0.001, minx-0.001, maxy+0.001, maxx+0.001))
        json.dump({"type":"FeatureCollection","features":fitur}, open(CACHE,"w"), ensure_ascii=False)
        print("unduhan disimpan ke", CACHE, file=sys.stderr)

    print(f"desa terbaca: {len(desa)}, fitur OSM: {len(fitur)}, "
          f"berlabel highway: {sum(1 for f in fitur if (f.get('properties') or {}).get('highway'))}",
          file=sys.stderr)
    if not desa: sys.exit("File desa 35?13?15?20*.geojson tidak ditemukan di --folder")
    to_m = Transformer.from_crs(4326, 32749, always_xy=True).transform  # UTM 49S
    hasil = []
    for f in fitur:
        g = f.get("geometry")
        if not g or g["type"] not in ("LineString", "MultiLineString"): continue
        p = f["properties"]
        hw = p.get("highway")
        if hw is None: continue
        if not a.semua and hw not in HIGHWAY_JALAN: continue
        garis = shape(g)
        # potong per desa (sekaligus terpotong ke kecamatan)
        for nama, kode, poly in desa:
            if not garis.intersects(poly): continue
            bagian = garis.intersection(poly)
            if bagian.geom_type == "GeometryCollection":
                from shapely.ops import linemerge
                gar = [x for x in bagian.geoms if x.geom_type in ("LineString","MultiLineString")]
                if not gar: continue
                bagian = linemerge(gar) if len(gar) > 1 else gar[0]
            if bagian.is_empty or bagian.geom_type not in ("LineString","MultiLineString"): continue
            panjang = round(transform(to_m, bagian).length, 1)
            if panjang < 1: continue
            hasil.append({"type":"Feature","geometry":mapping(bagian),"properties":{
                "osm_id": p.get("id") or p.get("@id"), "nama": p.get("name"), "highway": hw,
                "surface": p.get("surface"), "ref": p.get("ref"),
                "desa": nama, "kode_desa": kode, "panjang_m": panjang}})
    json.dump({"type":"FeatureCollection","features":hasil}, open(a.out,"w"), ensure_ascii=False)
    print(len(hasil), "segmen ditulis ke", a.out)
    ring = {}
    for h in hasil:
        k = (h["properties"]["desa"], h["properties"]["highway"])
        ring[k] = ring.get(k, 0) + h["properties"]["panjang_m"]
    for (d, hw), m in sorted(ring.items()): print(f"{d:25s} {hw:15s} {m/1000:7.2f} km")

if __name__ == "__main__":
    main()