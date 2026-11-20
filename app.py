"""BersihPoin - klik dua kali Buka BersihPoin.bat; data lokal disimpan di data.json."""
import json
import os
import secrets
import threading
import uuid
import webbrowser
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
FOLDER = os.path.dirname(os.path.abspath(__file__))
DB = "/tmp/data.json"
AKUN = "/tmp/akun.json"
TPS_DB = "/tmp/tps.json"
ADUAN_DB = "/tmp/aduan.json"
ARMADA_DB = "/tmp/armada.json"
SECRET = os.path.join(FOLDER, "secret.key")
LOKASI = []
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
AMBANG_PERINGATAN = 0.8
BATAS_PETA = {"barat": 105.75, "timur": 106.45, "selatan": -6.25, "utara": -5.7}


def baca_kunci():
    try:
        with open(SECRET, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        with open(SECRET, "w", encoding="utf-8") as f:
            f.write(key)
        return key


app.secret_key = os.environ.get("SECRET_KEY", "kunci-rahasia-sementara-123")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

def baca():
    try:
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise RuntimeError("data.json rusak dan tidak dapat dibaca; file tidak ditimpa.") from exc


def simpan_json(path, data):
    sementara = path + ".tmp"
    with open(sementara, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(sementara, path)


def baca_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{os.path.basename(path)} rusak dan tidak dapat dibaca.") from exc


def simpan(rows):
    simpan_json(DB, rows)


def baca_tps():
    rows = baca_json(TPS_DB, [])
    if not isinstance(rows, list):
        raise RuntimeError("Format data TPS tidak valid.")
    return rows


def cari_tps(nama):
    nama = nama_tps(nama)
    return next((t for t in baca_tps() if t.get("nama", "").casefold() == nama.casefold()), None)


def berat_hari_ini(nama):
    hari_ini = date.today().isoformat()
    return round(sum(
        float(r.get("berat", 0)) for r in baca()
        if r.get("tanggal") == hari_ini and nama_tps(r.get("lokasi")) == nama
    ), 1)


def data_tps_public(tps):
    berat = berat_hari_ini(tps["nama"])
    kapasitas = float(tps.get("kapasitas", 150))
    return {
        "nama": tps["nama"], "alamat": tps.get("alamat", ""),
        "lat": tps.get("lat"), "lng": tps.get("lng"),
        "kapasitas": kapasitas, "berat_hari_ini": berat,
        "isi": min(berat / kapasitas, 1) if kapasitas else 0,
    }


def nama_tps(value):
    if not isinstance(value, str):
        return ""
    nama = " ".join(value.split())
    if nama.casefold() == "tps":
        return ""
    if nama[:4].casefold() == "tps ":
        nama = nama[4:].strip()
    if not nama:
        return ""
    return f"TPS {nama}"


def baca_akun():
    try:
        with open(AKUN, encoding="utf-8") as f:
            akun = json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise RuntimeError("akun.json rusak dan tidak dapat dibaca.") from exc
    if not isinstance(akun, dict) or not isinstance(akun.get("username"), str) or not isinstance(akun.get("password"), str):
        raise RuntimeError("Format akun.json tidak valid.")
    return akun


def perlu_login(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            if request.path.startswith("/api/"):
                return jsonify(error="Silakan login kembali."), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def prediksi(rows, kapasitas=150.0, maks_hari=3, hari=7, bobot_hujan=0.5, bobot_tren=1.0):
    per, catatan_hujan = {}, {}
    for r in rows:
        d = date.fromisoformat(r["tanggal"])
        per[d] = per.get(d, 0.0) + float(r["berat"])
        if r.get("hujan") is not None:
            catatan_hujan.setdefault(d, []).append(float(r["hujan"]))
    if len(per) < 3:
        return {"cukup": False, "jumlah_hari": len(per)}

    tgl = sorted(per)
    ys = [per[d] for d in tgl]
    rata = sum(ys) / len(ys)

    faktor = []
    for w in range(7):
        v = [per[d] for d in tgl if d.weekday() == w]
        faktor.append(((sum(v) + rata) / (len(v) + 1)) / rata)

    des = [per[d] / faktor[d.weekday()] for d in tgl]
    level = des[0]
    for y in des[1:]:
        level = 0.4 * y + 0.6 * level
    xs = [(d - tgl[0]).days for d in tgl][-14:]
    zs = des[-14:]
    mx, mz = sum(xs) / len(xs), sum(zs) / len(zs)
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (z - mz) for x, z in zip(xs, zs)) / den if den else 0.0
    sd = (sum((z - mz) ** 2 for z in zs) / len(zs)) ** 0.5

    hujan_harian = {d: sum(v) / len(v) for d, v in catatan_hujan.items()}
    pasangan_hujan = [(per[d], hujan_harian[d]) for d in hujan_harian if d in per]
    rata_hujan = sum(h for _, h in pasangan_hujan) / len(pasangan_hujan) if pasangan_hujan else 0.0
    rata_berat_hujan = sum(kg for kg, _ in pasangan_hujan) / len(pasangan_hujan) if pasangan_hujan else 0.0
    var_hujan = sum((h - rata_hujan) ** 2 for _, h in pasangan_hujan)
    pengaruh_hujan = (
        sum((h - rata_hujan) * (kg - rata_berat_hujan) for kg, h in pasangan_hujan) / var_hujan
        if var_hujan else 0.0
    )
    hujan_per_hari = {}
    for w in range(7):
        nilai = [hujan_harian[d] for d in hujan_harian if d.weekday() == w]
        hujan_per_hari[w] = sum(nilai) / len(nilai) if nilai else rata_hujan

    awal = max(tgl[-1], date.today()) + timedelta(days=1)
    akum, sejak, out, batas_pertama = 0.0, 0, [], None
    for h in range(hari):
        d = awal + timedelta(days=h)
        langkah = (d - tgl[-1]).days
        tren = bobot_tren * slope * sum(0.8 ** i for i in range(1, langkah + 1))
        f = faktor[d.weekday()]
        dasar = max(0.0, (level + tren) * f)
        hujan = hujan_per_hari[d.weekday()]
        koreksi_hujan = pengaruh_hujan * (hujan - rata_hujan) * bobot_hujan
        koreksi_hujan = max(-dasar * 0.5, min(koreksi_hujan, dasar * 0.5))
        kg = max(0.0, dasar + koreksi_hujan)
        akum += kg
        sejak += 1
        penuh = akum >= kapasitas
        mendekati_batas = akum >= kapasitas * AMBANG_PERINGATAN
        angkut = penuh or mendekati_batas or sejak >= maks_hari
        if penuh and batas_pertama is None:
            batas_pertama = d.isoformat()
        out.append({
            "tanggal": d.isoformat(), "hari": HARI[d.weekday()], "kg": round(kg, 1),
            "bawah": round(max(0.0, kg - 1.28 * sd * f), 1), "atas": round(kg + 1.28 * sd * f, 1),
            "akum": round(akum, 1), "isi": round(akum / kapasitas, 3),
            "hujan": round(hujan, 1), "batas_tercapai": penuh,
            "mendekati_batas": mendekati_batas, "angkut": angkut,
            "alasan": (
                "batas maksimal berat tercapai" if penuh
                else "berat sudah mencapai 80% kapasitas" if mendekati_batas
                else "sudah terlalu lama"
            ) if angkut else "",
        })
        if angkut:
            akum, sejak = 0.0, 0
    jadwal = [x for x in out if x["angkut"]]
    return {
        "cukup": True, "hari": out, "kapasitas": kapasitas, "data_hari": len(per),
        "total": round(sum(x["kg"] for x in out), 1), "jumlah_angkut": len(jadwal),
        "angkut_pertama": jadwal[0]["tanggal"] if jadwal else None,
        "batas_pertama": batas_pertama, "ambang_peringatan": AMBANG_PERINGATAN,
        "bobot_hujan": round(bobot_hujan * 100),
        "bobot_tren": round(bobot_tren * 100),
        "riwayat": [
            {"tanggal": d.isoformat(), "kg": round(per[d], 1),
             "hujan": round(hujan_harian[d], 1) if d in hujan_harian else None}
            for d in tgl[-14:]
        ],
    }


DASHBOARD_SCRIPT = r"""
const $ = s => document.querySelector(s);
const st = { lokasi: "", sel: 0, hasil: null };
const angka = n => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n);
const tgl = (iso, o) => new Date(iso + "T00:00").toLocaleDateString("id-ID", o);
const warna = f => (f < 0.5 ? "var(--daun)" : f < 0.8 ? "var(--kuning)" : "var(--koral)");
const api = (u, o) => fetch(u, o).then(r => r.json());
const kirim = (u, m, b) => api(u, { method: m, headers: { "Content-Type": "application/json" }, body: b && JSON.stringify(b) });

let tm;
function toast(t) {
  const e = $("#toast"); e.textContent = t; e.classList.add("tampil");
  clearTimeout(tm); tm = setTimeout(() => e.classList.remove("tampil"), 2200);
}

const PATH = "M12 32h56l-5 68q-.6 5-5 5H22q-4.4 0-5-5z";
const tong = (i, f) => `<svg viewBox="0 0 80 112" aria-hidden="true">
  <defs><clipPath id="c${i}"><path d="${PATH}"/></clipPath></defs>
  <path d="${PATH}" fill="var(--tong)"/>
  <g clip-path="url(#c${i})"><rect class="isi" x="0" y="32" width="80" height="74" fill="${warna(f)}" style="--s:${Math.min(f, 1)};transition-delay:${i * 90}ms"/></g>
  <path d="${PATH}" fill="none" stroke="var(--garis)" stroke-width="2.5" stroke-linejoin="round"/>
  <g class="tutup"><rect x="7" y="22" width="66" height="9" rx="4.5" fill="var(--tutup)" stroke="var(--garis)" stroke-width="2"/><rect x="31" y="15" width="18" height="8" rx="3" fill="var(--tutup)" stroke="var(--garis)" stroke-width="2"/></g>
</svg>`;

async function muat() {
  const q = new URLSearchParams({
    lokasi: st.lokasi, kapasitas: $("#kap").value, maks: $("#maks").value,
    bobot_hujan: $("#bobotHujan").value, bobot_tren: $("#bobotTren").value
  });
  st.hasil = await api("/api/prediksi?" + q);
  gambar();
  riwayat();
}

function gambar() {
  const h = st.hasil, kotak = $("#tongs");
  kotak.classList.remove("go");
  if (!h.cukup) {
    kotak.innerHTML = Array.from({ length: 7 }, (_, i) => `<div class="bin" style="cursor:default">${tong(i, 0)}<small>hari ke-${i + 1}</small></div>`).join("");
    $("#ringkas").textContent = "Tong masih kosong karena datanya belum cukup.";
    $("#peringatan").innerHTML = "";
    $("#grafik").innerHTML = '<p class="grafik-kosong">Grafik akan tersedia setelah ada catatan dari minimal 3 hari berbeda.</p>';
    $("#detail").innerHTML = `<div class="kosong"><p>Baru ada ${h.jumlah_hari} hari data. Catat minimal 3 hari berbeda untuk melihat prakiraan.</p></div>`;
    $("#truk").classList.remove("ada");
    return;
  }
  kotak.innerHTML = h.hari.map((d, i) => `<button class="bin" data-i="${i}" aria-pressed="${i === st.sel}">
    ${d.angkut ? '<span class="angkut">Truk datang</span>' : ""}${tong(i, d.isi)}
    <b>${d.hari.slice(0, 3)}</b><small>${tgl(d.tanggal, { day: "numeric", month: "short" })}</small><span class="kg">${angka(d.kg)} kg</span></button>`).join("");
  kotak.querySelectorAll(".bin").forEach(b => b.onclick = () => { st.sel = +b.dataset.i; kotak.querySelectorAll(".bin").forEach(x => x.setAttribute("aria-pressed", x === b)); detail(); });
  requestAnimationFrame(() => requestAnimationFrame(() => kotak.classList.add("go")));
  const p = h.hari.findIndex(d => d.angkut), truk = $("#truk");
  truk.classList.toggle("ada", p >= 0);
  if (p >= 0) truk.style.left = ((p + 0.5) / 7) * 100 + "%";
  $("#ringkas").textContent = `Diperkirakan ${angka(h.total)} kg dalam 7 hari. ` + (h.jumlah_angkut
    ? `Truk cukup datang ${h.jumlah_angkut} kali, yang pertama hari ${tgl(h.angkut_pertama, { weekday: "long" })}.` : "Belum perlu ada pengangkutan minggu ini.");
  const batas = h.hari.find(d => d.mendekati_batas || d.batas_tercapai);
  $("#peringatan").innerHTML = batas
    ? `<div class="peringatan ${batas.batas_tercapai ? "kritis" : ""}" role="alert"><strong>${batas.batas_tercapai ? "Peringatan: kapasitas armada terlampaui" : "Perhatian: TPS mendekati penuh"}</strong><span>Prakiraan ${angka(batas.akum)} kg (${Math.round(batas.isi * 100)}% dari kapasitas ${angka(h.kapasitas)} kg) pada ${tgl(batas.tanggal, { weekday: "long", day: "numeric", month: "long" })}. Jadwalkan pengangkutan pada hari itu.</span></div>`
    : "";
  grafik();
  detail();
}

function grafik() {
  const h = st.hasil, data = h.hari, riwayat = h.riwayat;
  const W = 760, H = 270, kiri = 52, kanan = 48, atas = 22, bawah = 48;
  const lebar = W - kiri - kanan, tinggi = H - atas - bawah, langkah = lebar / data.length;
  const maxKg = Math.max(h.kapasitas, ...data.map(d => Math.max(d.akum, d.kg)), 1);
  const maxHujan = Math.max(...data.map(d => d.hujan), 1);
  const yKg = n => atas + tinggi * (1 - n / maxKg);
  const yHujan = n => atas + tinggi * (1 - n / maxHujan);
  const x = i => kiri + langkah * (i + .5);
  const grid = [0, .5, 1].map(f => {
    const y = atas + tinggi * (1 - f);
    return `<line x1="${kiri}" y1="${y}" x2="${W - kanan}" y2="${y}" class="grid"/><text x="${kiri - 8}" y="${y + 4}" text-anchor="end" class="label">${angka(maxKg * f)}</text><text x="${W - kanan + 8}" y="${y + 4}" class="label">${angka(maxHujan * f)}</text>`;
  }).join("");
  const bars = data.map((d, i) => `<rect x="${x(i) - langkah * .18}" y="${yKg(d.kg)}" width="${langkah * .36}" height="${atas + tinggi - yKg(d.kg)}" rx="4" class="bar" aria-label="${angka(d.kg)} kg sampah"/>`).join("");
  const points = data.map((d, i) => `${x(i)},${yKg(d.akum)}`).join(" ");
  const rain = data.map((d, i) => `${x(i)},${yHujan(d.hujan)}`).join(" ");
  const limitY = yKg(h.kapasitas);
  const nearLimitY = yKg(h.kapasitas * h.ambang_peringatan);
  const days = data.map((d, i) => `<text x="${x(i)}" y="${H - 20}" text-anchor="middle" class="label">${d.hari.slice(0, 3)}</text>`).join("");
  const historyNote = riwayat.length ? ` ${riwayat.length} hari riwayat digunakan untuk prakiraan.` : "";
  $("#grafik").innerHTML = `<svg class="grafik-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Grafik prakiraan bobot sampah, akumulasi, batas maksimal, dan curah hujan untuk 7 hari ke depan">
    ${grid}${bars}<line x1="${kiri}" y1="${nearLimitY}" x2="${W - kanan}" y2="${nearLimitY}" class="batas-dekat"/><line x1="${kiri}" y1="${limitY}" x2="${W - kanan}" y2="${limitY}" class="batas"/>
    <polyline points="${points}" class="garis-akumulasi"/><polyline points="${rain}" class="garis-hujan"/>
    ${data.map((d, i) => `<circle cx="${x(i)}" cy="${yKg(d.akum)}" r="4" class="titik-akumulasi"/><circle cx="${x(i)}" cy="${yHujan(d.hujan)}" r="3.5" class="titik-hujan"/>`).join("")}${days}
  </svg>
  <div class="legenda"><span><i class="swatch sampah"></i>Sampah harian (kg)</span><span><i class="swatch akumulasi"></i>Bobot tong (kg)</span><span><i class="swatch batas-dekat"></i>Peringatan 80%</span><span><i class="swatch batas"></i>Batas maksimal (${angka(h.kapasitas)} kg)</span><span><i class="swatch hujan"></i>Curah hujan (mm)</span></div>
  <p class="grafik-catatan">Sumbu kiri: kg · sumbu kanan: mm · Hujan diprakirakan dari rata-rata catatan pada hari yang sama.${historyNote}</p>`;
}

function detail() {
  const d = st.hasil.hari[st.sel], pct = Math.round(d.isi * 100);
  $("#detail").innerHTML = `<strong>${tgl(d.tanggal, { weekday: "long", day: "numeric", month: "long" })}</strong>
    <p>Sampah masuk diperkirakan ${angka(d.kg)} kg (kisaran ${angka(d.bawah)} sampai ${angka(d.atas)} kg), dengan curah hujan ${angka(d.hujan)} mm. Isi tong menjadi ${angka(d.akum)} kg dari batas ${angka(st.hasil.kapasitas)} kg, atau ${pct}%.</p>
    <p>${d.angkut ? `<b>Truk sebaiknya datang hari ini</b> karena ${d.alasan}.` : "Belum perlu diangkut, tong masih muat."}</p>
    <div class="meter"><i style="width:${Math.min(pct, 100)}%;background:${warna(d.isi)}"></i></div>`;
}

async function riwayat() {
  const rows = await api("/api/data?lokasi=" + encodeURIComponent(st.lokasi));
  $("#riwayat").innerHTML = rows.length ? rows.slice(0, 8).map(r => `<li><span>${angka(r.berat)} kg<small>${tgl(r.tanggal, { weekday: "short", day: "numeric", month: "short" })}, ${aman(r.lokasi)}</small></span><button data-id="${r.id}" aria-label="Hapus catatan">×</button></li>`).join("")
    : '<li><span>Belum ada catatan.</span></li>';
  document.querySelectorAll("#riwayat button").forEach(b => b.onclick = async () => { await api("/api/data/" + b.dataset.id, { method: "DELETE" }); toast("Catatan dihapus"); muat(); });
}

const aman = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function muatLokasi() {
  const lokasi = await api("/api/lokasi");
  const nav = $("#lokasi");
  nav.replaceChildren();
  const semua = document.createElement("button");
  semua.textContent = "Semua TPS";
  semua.dataset.v = "";
  semua.classList.toggle("aktif", !st.lokasi);
  nav.append(semua);
  for (const nama of lokasi) {
    const tombol = document.createElement("button");
    tombol.textContent = nama;
    tombol.dataset.v = nama;
    tombol.classList.toggle("aktif", st.lokasi === nama);
    nav.append(tombol);
  }
  $("#daftarLokasi").replaceChildren(...lokasi.map(nama => {
    const opsi = document.createElement("option");
    opsi.value = nama;
    return opsi;
  }));
}

$("#form").onsubmit = async e => {
  e.preventDefault();
  const r = await kirim("/api/data", "POST", { tanggal: $("#tgl").value, berat: $("#berat").value, hujan: $("#hujan").value, lokasi: $("#lok").value.trim(), kapasitas: $("#kap").value });
  if (r.error) return toast(r.error);
  $("#berat").value = "";
  const p = r.peringatan;
  if (p.status) {
    const maksimum = p.status === "maksimum";
    $("#notifikasiAktual").innerHTML = `<div class="peringatan ${maksimum ? "kritis" : ""}" role="alert"><strong>${maksimum ? "Batas maksimum tercapai" : "TPS hampir mencapai batas"}</strong><span>${aman($("#lok").value.trim())}: ${angka(p.akumulasi)} kg dari kapasitas ${angka(p.kapasitas)} kg (${Math.round(p.akumulasi / p.kapasitas * 100)}%). ${maksimum ? "Segera lakukan pengangkutan hari ini." : "Jadwalkan pengangkutan segera."}</span></div>`;
    toast(maksimum ? "Peringatan: batas berat tercapai, angkut hari ini" : "Peringatan: berat sampah hampir mencapai batas");
  } else {
    $("#notifikasiAktual").innerHTML = "";
    toast("Data disimpan");
  }
  st.sel = 0; await muatLokasi(); muat();
};
$("#lokasi").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#lokasi button").forEach(x => x.classList.toggle("aktif", x === b));
  st.lokasi = b.dataset.v; if (b.dataset.v) $("#lok").value = b.dataset.v; st.sel = 0; muat();
};
$("#lok").onblur = () => {
  const nama = $("#lok").value.trim();
  if (nama && !/^TPS\s/i.test(nama)) $("#lok").value = "TPS " + nama;
};
for (const [id, out] of [["kap", "kapV"], ["maks", "maksV"], ["bobotHujan", "bobotHujanV"], ["bobotTren", "bobotTrenV"]]) {
  $("#" + id).oninput = e => { $("#" + out).textContent = e.target.value; clearTimeout(st.t); st.t = setTimeout(muat, 150); };
}
$("#tgl").value = new Date().toLocaleDateString("sv-SE");
async function mulai() { await muatLokasi(); await muat(); }
mulai();
"""


@app.get("/")
def beranda():
    return render_template("portals.html")


@app.get("/warga")
def portal_warga():
    return render_template("warga.html")


@app.get("/warga/aduan")
def halaman_aduan_warga():
    return render_template("warga_aduan.html")


@app.get("/edukasi")
def halaman_edukasi():
    return render_template("edukasi.html")


@app.get("/dashboard")
@perlu_login
def dashboard_lama():
    return render_template("index.html", lokasi=LOKASI, dashboard_script=DASHBOARD_SCRIPT)


@app.get("/operator")
@perlu_login
def portal_operator():
    return render_template("operator.html")


@app.get("/operator/tps")
@perlu_login
def halaman_tps():
    return render_template("tps.html")


@app.get("/operator/armada")
@perlu_login
def halaman_armada():
    return render_template("armada.html")


@app.get("/operator/aduan")
@perlu_login
def halaman_aduan():
    return render_template("aduan.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    akun = baca_akun()
    if session.get("username") and akun:
        return redirect(url_for("portal_operator"))

    pesan = ""
    setup = akun is None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if setup:
            if len(username) < 3 or len(username) > 40 or len(password) < 8:
                pesan = "Nama pengguna minimal 3 karakter dan kata sandi minimal 8 karakter."
            else:
                simpan_json(AKUN, {"username": username, "password": generate_password_hash(password)})
                session.clear()
                session["username"] = username
                session.permanent = True
                return redirect(url_for("portal_operator"))
        elif akun and username == akun["username"] and check_password_hash(akun["password"], password):
            session.clear()
            session["username"] = username
            session.permanent = True
            return redirect(url_for("portal_operator"))
        else:
            pesan = "Nama pengguna atau kata sandi salah."

    return render_template("login.html", setup=setup, pesan=pesan)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("beranda"))


@app.get("/api/public/tps")
def api_public_tps():
    return jsonify([data_tps_public(tps) for tps in baca_tps()])


@app.get("/api/public/data")
def api_public_data():
    lokasi = nama_tps(request.args.get("lokasi", ""))
    rows = [
        {"id": r.get("id"), "tanggal": r.get("tanggal"), "berat": r.get("berat"),
         "hujan": r.get("hujan"), "lokasi": nama_tps(r.get("lokasi"))}
        for r in baca()
        if not lokasi or nama_tps(r.get("lokasi")) == lokasi
    ]
    return jsonify(sorted(rows, key=lambda r: (r["tanggal"], r["id"] or ""), reverse=True))


@app.get("/api/public/prediksi")
def api_public_prediksi():
    lokasi = nama_tps(request.args.get("lokasi", ""))
    try:
        hari = min(max(int(request.args.get("hari", 7)), 1), 30)
    except ValueError:
        return jsonify(error="Jumlah hari harus berupa angka antara 1 dan 30."), 400
    tps = cari_tps(lokasi) if lokasi else None
    kapasitas = float(tps.get("kapasitas", 150)) if tps else 150
    rows = [r for r in baca() if not lokasi or nama_tps(r.get("lokasi")) == lokasi]
    return jsonify(prediksi(rows, kapasitas=kapasitas, hari=hari))


@app.post("/api/public/aduan")
def api_public_aduan():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Format permintaan tidak valid."), 400
    nama_input = body.get("nama", "")
    isi_input = body.get("isi", "")
    if not isinstance(nama_input, str) or not isinstance(isi_input, str):
        return jsonify(error="Nama dan isi aduan harus berupa teks."), 400
    tps = cari_tps(body.get("tps"))
    nama = " ".join(nama_input.split())[:80]
    isi = " ".join(isi_input.split())
    if not tps:
        return jsonify(error="Pilih TPS yang terdaftar."), 400
    if not isi or len(isi) > 2000:
        return jsonify(error="Isi aduan wajib diisi (maksimal 2.000 karakter)."), 400
    rows = baca_json(ADUAN_DB, [])
    aduan = {
        "id": uuid.uuid4().hex[:12], "tps": tps["nama"], "nama": nama,
        "isi": isi, "waktu": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "baru",
    }
    rows.append(aduan)
    simpan_json(ADUAN_DB, rows)
    return jsonify(ok=True, aduan={"id": aduan["id"], "waktu": aduan["waktu"]}), 201


@app.get("/api/operator/tps")
@perlu_login
def api_operator_tps():
    return jsonify([data_tps_public(tps) for tps in baca_tps()])


@app.post("/api/operator/tps")
@perlu_login
def api_simpan_tps():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Format permintaan tidak valid."), 400
    nama = nama_tps(body.get("nama"))
    alamat = " ".join(str(body.get("alamat", "")).split())
    try:
        lat, lng = float(body.get("lat")), float(body.get("lng"))
        kapasitas = float(body.get("kapasitas", 150))
    except (ValueError, TypeError):
        return jsonify(error="Koordinat dan kapasitas harus berupa angka."), 400
    if not nama or len(nama) > 100 or len(alamat) > 200:
        return jsonify(error="Nama TPS dan alamat wajib diisi dengan panjang yang valid."), 400
    if not BATAS_PETA["selatan"] <= lat <= BATAS_PETA["utara"] or not BATAS_PETA["barat"] <= lng <= BATAS_PETA["timur"]:
        return jsonify(error="Titik TPS harus berada di Cilegon dan sekitarnya."), 400
    if not 10 <= kapasitas <= 5000:
        return jsonify(error="Kapasitas harus antara 10 dan 5.000 kg."), 400
    tps_rows = baca_tps()
    lama = next((t for t in tps_rows if t.get("nama", "").casefold() == nama.casefold()), None)
    record = {"nama": nama, "alamat": alamat, "lat": lat, "lng": lng, "kapasitas": kapasitas}
    if lama:
        lama.update(record)
    else:
        tps_rows.append(record)
    simpan_json(TPS_DB, tps_rows)
    return jsonify(ok=True, tps=data_tps_public(record)), 201 if not lama else 200


@app.post("/api/operator/data")
@perlu_login
def api_operator_data():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Format permintaan tidak valid."), 400
    tps = cari_tps(body.get("tps"))
    if not tps:
        return jsonify(error="Pilih TPS yang terdaftar sebelum memasukkan data."), 400
    try:
        tanggal = date.fromisoformat(body.get("tanggal", "")).isoformat()
        berat = float(body.get("berat"))
        hujan = float(body.get("hujan", 0))
    except (ValueError, TypeError):
        return jsonify(error="Isi tanggal, berat, dan curah hujan dengan benar."), 400
    if not 0 < berat <= 100000 or not 0 <= hujan <= 500:
        return jsonify(error="Berat harus lebih dari 0 kg dan curah hujan 0–500 mm."), 400
    rows = baca()
    rows.append({
        "id": uuid.uuid4().hex[:8], "tanggal": tanggal, "berat": round(berat, 1),
        "hujan": round(hujan, 1), "lokasi": tps["nama"],
    })
    simpan(rows)
    akumulasi = round(sum(
        float(r["berat"]) for r in rows
        if r["tanggal"] == tanggal and nama_tps(r.get("lokasi")) == tps["nama"]
    ), 1)
    status = "maksimum" if akumulasi >= tps["kapasitas"] else "hampir" if akumulasi >= tps["kapasitas"] * AMBANG_PERINGATAN else None
    return jsonify(ok=True, akumulasi=akumulasi, kapasitas=tps["kapasitas"], status=status), 201


@app.get("/api/operator/aduan")
@perlu_login
def api_operator_aduan():
    lokasi = nama_tps(request.args.get("tps", ""))
    rows = baca_json(ADUAN_DB, [])
    return jsonify(sorted(
        [r for r in rows if not lokasi or nama_tps(r.get("tps")) == lokasi],
        key=lambda r: r["waktu"], reverse=True,
    ))


@app.patch("/api/operator/aduan/<aid>")
@perlu_login
def api_tandai_aduan(aid):
    rows = baca_json(ADUAN_DB, [])
    aduan = next((r for r in rows if r.get("id") == aid), None)
    if not aduan:
        return jsonify(error="Aduan tidak ditemukan."), 404
    aduan["status"] = "ditangani"
    aduan["waktu_ditangani"] = datetime.now().astimezone().isoformat(timespec="seconds")
    simpan_json(ADUAN_DB, rows)
    return jsonify(ok=True)


def status_armada(armada):
    tps = cari_tps(armada.get("tps"))
    isi = berat_hari_ini(armada.get("tps")) / float(tps.get("kapasitas", 150)) if tps else 0
    if armada.get("status") == "mengangkut":
        return "mengangkut"
    return "butuh_angkut" if isi >= AMBANG_PERINGATAN else "siaga"


@app.get("/api/operator/armada")
@perlu_login
def api_operator_armada():
    rows = baca_json(ARMADA_DB, [])
    for armada in rows:
        armada["status_efektif"] = status_armada(armada)
    return jsonify(rows)


@app.post("/api/operator/armada")
@perlu_login
def api_tambah_armada():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Format permintaan tidak valid."), 400
    nama = " ".join(str(body.get("nama", "")).split())[:80]
    tps = cari_tps(body.get("tps"))
    if not nama or not tps:
        return jsonify(error="Nama armada dan TPS wajib dipilih."), 400
    rows = baca_json(ARMADA_DB, [])
    item = {"id": uuid.uuid4().hex[:12], "nama": nama, "tps": tps["nama"], "status": "siaga"}
    rows.append(item)
    simpan_json(ARMADA_DB, rows)
    item["status_efektif"] = status_armada(item)
    return jsonify(item), 201


@app.patch("/api/operator/armada/<aid>")
@perlu_login
def api_status_armada(aid):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Format permintaan tidak valid."), 400
    status = body.get("status")
    if status not in {"mengangkut", "siaga"}:
        return jsonify(error="Status armada tidak valid."), 400
    rows = baca_json(ARMADA_DB, [])
    armada = next((r for r in rows if r.get("id") == aid), None)
    if not armada:
        return jsonify(error="Armada tidak ditemukan."), 404
    armada["status"] = status
    simpan_json(ARMADA_DB, rows)
    armada["status_efektif"] = status_armada(armada)
    return jsonify(armada)


@app.get("/api/data")
@perlu_login
def api_data():
    lok = request.args.get("lokasi", "")
    rows = [dict(r, lokasi=nama_tps(r.get("lokasi"))) for r in baca() if not lok or nama_tps(r.get("lokasi")) == lok]
    return jsonify(sorted(rows, key=lambda r: (r["tanggal"], r["id"]), reverse=True))


@app.get("/api/lokasi")
@perlu_login
def api_lokasi():
    lokasi = []
    for row in baca():
        nama = nama_tps(row.get("lokasi"))
        if nama and nama not in lokasi:
            lokasi.append(nama)
    return jsonify(lokasi)


@app.post("/api/data")
@perlu_login
def api_tambah():
    b = request.get_json(silent=True) or {}
    try:
        tanggal = date.fromisoformat(b.get("tanggal", "")).isoformat()
        berat = float(b.get("berat"))
        kapasitas = float(b.get("kapasitas", 150))
    except (ValueError, TypeError):
        return jsonify(error="Isi tanggal, berat, dan kapasitas dengan benar."), 400
    try:
        hujan = float(b.get("hujan", 0))
    except (ValueError, TypeError):
        return jsonify(error="Curah hujan harus berupa angka antara 0 dan 500 mm."), 400
    lokasi = nama_tps(b.get("lokasi"))
    if not 0 < berat <= 100000 or not 0 <= hujan <= 500 or not 10 <= kapasitas <= 5000 or not lokasi or len(lokasi) > 100:
        return jsonify(error="Berat harus lebih dari 0 kg, curah hujan 0–500 mm, kapasitas 10–5000 kg, dan nama TPS harus diisi (maksimal 100 karakter)."), 400
    rows = baca()
    rows.append({"id": uuid.uuid4().hex[:8], "tanggal": tanggal, "berat": round(berat, 1), "hujan": round(hujan, 1), "lokasi": lokasi})
    simpan(rows)
    akumulasi = sum(
        float(r["berat"]) for r in rows
        if r["tanggal"] == tanggal and nama_tps(r.get("lokasi")) == lokasi
    )
    status_batas = (
        "maksimum" if akumulasi >= kapasitas
        else "hampir" if akumulasi >= kapasitas * AMBANG_PERINGATAN
        else None
    )
    return jsonify(
        ok=True,
        peringatan={
            "status": status_batas,
            "akumulasi": round(akumulasi, 1),
            "kapasitas": kapasitas,
            "tanggal": tanggal,
        },
    ), 201


@app.delete("/api/data/<rid>")
@perlu_login
def api_hapus(rid):
    simpan([r for r in baca() if r["id"] != rid])
    return jsonify(ok=True)


@app.get("/api/prediksi")
@perlu_login
def api_prediksi():
    try:
        kap = min(max(float(request.args.get("kapasitas", 150)), 10), 5000)
        maks = min(max(int(request.args.get("maks", 3)), 1), 7)
        bobot_hujan = min(max(float(request.args.get("bobot_hujan", 50)), 0), 100) / 100
        bobot_tren = min(max(float(request.args.get("bobot_tren", 100)), 0), 100) / 100
    except ValueError:
        return jsonify(error="Parameter tidak valid."), 400
    lok = request.args.get("lokasi", "")
    return jsonify(prediksi([r for r in baca() if not lok or nama_tps(r.get("lokasi")) == lok], kap, maks, bobot_hujan=bobot_hujan, bobot_tren=bobot_tren))


if __name__ == "__main__":
    threading.Timer(1.0, webbrowser.open, args=("http://127.0.0.1:5000",)).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
