# LocalVault

LocalVault adalah password manager untuk satu pemilik. Satu proses pada komputer
host menyimpan vault terenkripsi di PostgreSQL dan menyajikan antarmuka web ke
browser di komputer yang sama atau perangkat lain pada LAN.

> **Status validasi lokal (23 Juli 2026):** `npm test` (7 test) dan
> `npm run build` lulus. Test backend tidak tersedia pada workspace saat ini,
> sehingga tidak ada hasil pytest backend yang dapat dilaporkan. Ini adalah
> validasi source lokal, bukan klaim bahwa seluruh acceptance test SRS §15 sudah
> lulus.

## Fitur utama

- akun pengguna dengan vault terenkripsi per pengguna, master password, dan recovery key opsional;
- AES-256-GCM untuk payload vault dan Argon2id untuk penurunan kunci;
- credential, kategori, tag, favorite, custom field Text/Secret, dan password
  history;
- pencarian, filter, sort, bulk action, Trash, restore, dan purge;
- generator password berbasis CSPRNG;
- impor CSV dengan preview/mapping dan ekspor CSV berdasarkan profile/scope;
- backup `.lvbak` terenkripsi, snapshot otomatis, retensi, dan restore;
- sinkronisasi antartab/perangkat melalui WebSocket;
- UI Indonesia/English, tema terang/gelap, dan layout responsif;
- launcher host lokal/native dengan tray, daftar alamat LAN, lock-all, autostart, dan
  shutdown tertib.

## Batas keamanan yang wajib dipahami

LocalVault melindungi data **saat tersimpan**. Payload vault dan backup disimpan
dalam envelope terenkripsi. Aplikasi tidak memakai cloud, CDN, telemetry,
breach lookup, atau koneksi keluar otomatis.

LocalVault v1 menggunakan **HTTP dan WebSocket tanpa TLS** pada LAN. Perangkat di
jalur jaringan dapat membaca atau mengubah master password, token sesi, dan
secret yang dibuka. Karena itu:

- gunakan hanya pada LAN tepercaya dan jangan melakukan port-forward port
  LocalVault ke internet;
- selesaikan setup pertama pada jaringan tepercaya—klien LAN pertama yang
  mencapai host baru dapat mengambil alih setup;
- anggap host, OS, browser, akun OS, process memory, layar, dan clipboard sebagai
  bagian tepercaya;
- jangan mengandalkan LocalVault untuk melindungi data dari malware, keylogger,
  browser/host yang terkompromi, atau pengguna yang memperoleh sesi unlocked;
- tidak ada rate limit atau account lockout pada v1;
- ekspor CSV adalah **plaintext** pada perangkat yang mengunduhnya. Amankan dan
  hapus file tersebut setelah digunakan.

Detail lengkap tersedia di [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Alur akun dan login

Halaman awal selalu menampilkan login. Pada database kosong, pilih **Buat akun
pertama**, lalu isi username, email, master password, bahasa, pilihan recovery
key, dan acknowledgement risiko HTTP LAN. Form tersebut membuat akun melalui
`/api/v1/register`, lalu langsung membuka vault.

Setelah akun pertama dibuat, setup ditutup dan tombol pembuatan akun tidak lagi
ditampilkan. Akses berikutnya menggunakan username atau email serta master
password melalui login. Recovery key hanya ditampilkan satu kali jika opsi
recovery diaktifkan; simpan di tempat aman karena LocalVault tidak menyediakan
pemulihan oleh pihak ketiga. HTTP LAN tidak terenkripsi, sehingga setup dan
login hanya boleh dilakukan pada jaringan tepercaya.

## Development dari source

Baseline yang digunakan CI:

- Python 3.13;
- Node.js 24.x. Vite yang dipin memerlukan minimal Node `20.19.0` atau
  `22.12.0+` pada major yang lebih baru.
- PostgreSQL 18 lokal untuk menjalankan backend dari source dan integration test.

Dependency runtime dan development dipisahkan di
`backend/requirements-*.txt`. `backend/requirements.lock` mengunci dependency
transitif beserta hash; `package-lock.json` adalah lockfile frontend.

### Setup Windows PowerShell

```powershell
py -3.13 -m venv backend/.venv313
& .\backend\.venv313\Scripts\python.exe -m pip install --require-hashes -r backend/requirements.lock
npm ci
```

### Setup macOS/Linux

```bash
python3.13 -m venv backend/.venv313
backend/.venv313/bin/python -m pip install --require-hashes -r backend/requirements.lock
npm ci
```

Sebelum menjalankan backend, pastikan PostgreSQL 18 aktif, menerima koneksi pada
`127.0.0.1:5432`, dan database `localvault` serta user `localvault` tersedia.
Periksa konektivitas dengan:

```powershell
pg_isready -h 127.0.0.1 -p 5432 -d localvault -U localvault
```

```bash
pg_isready -h 127.0.0.1 -p 5432 -d localvault -U localvault
```

Backend source wajib dijalankan dengan `DATABASE_URL` lokal eksplisit. Jalankan
urutan berikut dari dua atau tiga terminal sesuai kebutuhan.

1. Di terminal backend, dari root repository:

   Windows PowerShell:

   ```powershell
   $env:DATABASE_URL = "postgresql://localvault:localvault@127.0.0.1:5432/localvault"
   Set-Location backend
   & .\.venv313\Scripts\python.exe run.py
   ```

   macOS/Linux:

   ```bash
   export DATABASE_URL="postgresql://localvault:localvault@127.0.0.1:5432/localvault"
   cd backend
   .venv313/bin/python run.py
   ```

2. Di terminal lain, dari root repository, build frontend:

   ```bash
   npm run build
   ```

3. Untuk hot reload frontend, biarkan backend berjalan dan jalankan dari root:

   ```bash
   npm run dev
   ```

`run.py` menjalankan server ASGI langsung pada port `8741` dan bind ke seluruh
alamat IPv4 host (`0.0.0.0`). Host launcher lokal menjalankan
`QApplication`/tray pada main thread dan Uvicorn pada worker thread. Konfigurasi,
backup, log, dan instance lock disimpan pada direktori `LOCALVAULT_DATA_DIR`;
default source adalah `backend/LocalVault-Data`. Database PostgreSQL dibaca dari
`DATABASE_URL`. Jangan gunakan data nyata sebagai fixture pengujian.

Buka URL yang ditampilkan Vite (umumnya `http://127.0.0.1:5173`). Proxy development
meneruskan request `/api` ke `http://127.0.0.1:8741`.

## Build, test, dan audit

```bash
npm run build
npm test
npm run test:e2e
npm run audit
```

Backend (jalankan dari direktori `backend` dengan PostgreSQL tersedia dan
`DATABASE_URL` lokal eksplisit):

```powershell
$env:DATABASE_URL = "postgresql://localvault:localvault@127.0.0.1:5432/localvault"
Set-Location backend
& .\.venv313\Scripts\python.exe -m pytest -q
```

```bash
export DATABASE_URL="postgresql://localvault:localvault@127.0.0.1:5432/localvault"
cd backend
.venv313/bin/python -m pytest -q
```

Test backend tidak tersedia pada workspace saat ini dan tidak dijalankan oleh
perintah di atas. Hasil frontend juga tidak menutup seluruh acceptance test SRS
§15.

Playwright memerlukan browser test yang sesuai. Instalasinya dapat dilakukan
dengan `npx playwright install` pada mesin development/CI. Test wajib memakai
direktori terisolasi dan tidak boleh menyentuh `backend/LocalVault-Data` pengguna.

Audit dependency Python yang digunakan dalam verifikasi:

```bash
uvx pip-audit -r backend/requirements.lock
```

## Struktur repository

```text
localVault/
├── backend/
│   ├── localvault/          # FastAPI, domain, crypto, services, launcher
│   └── requirements*.txt    # dependency direct dan lock transitif
├── src/                     # React, TypeScript, i18n, dan unit tests
├── tests/e2e/               # Playwright workflows
├── docs/                    # threat model serta recovery/upgrade
└── SRS.md                   # kontrak normatif LocalVault v1
```

## Dokumentasi

- [SRS.md](SRS.md) — kontrak normatif dan acceptance test v1;
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) — batas perlindungan dan risiko;
- [docs/RECOVERY_AND_UPGRADE.md](docs/RECOVERY_AND_UPGRADE.md) — backup, restore,
  recovery, dan upgrade aman.

## Lisensi

LocalVault tersedia di bawah [MIT License](LICENSE).
