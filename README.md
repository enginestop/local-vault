# LocalVault

LocalVault adalah password manager portable untuk satu pemilik. Satu proses pada
komputer host menyimpan vault terenkripsi dan menyajikan antarmuka web ke browser
di komputer yang sama atau perangkat lain pada LAN.

> **Status pengembangan:** source code dan pengujian lokal tersedia, tetapi build
> v1 belum boleh dianggap sebagai release tervalidasi. Sejumlah gate SRS §15 masih
> memerlukan pengujian browser nyata, clean-machine lintas OS, fault/power-loss,
> performa, dan hash artefak final. Lihat [VERIFICATION.md](VERIFICATION.md).

## Fitur utama

- vault satu pengguna dengan master password dan recovery key opsional;
- AES-256-GCM untuk payload vault dan Argon2id untuk penurunan kunci;
- credential, kategori, tag, favorite, custom field Text/Secret, dan password
  history;
- pencarian, filter, sort, bulk action, Trash, restore, dan purge;
- generator password berbasis CSPRNG;
- impor CSV dengan preview/mapping dan ekspor CSV berdasarkan profile/scope;
- backup `.lvbak` terenkripsi, snapshot otomatis, retensi, dan restore;
- sinkronisasi antartab/perangkat melalui WebSocket;
- UI Indonesia/English, tema terang/gelap, dan layout responsif;
- launcher native dengan tray, daftar alamat LAN, lock-all, autostart, dan
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

## Menjalankan paket portable

Target paket v1 adalah Windows 11 x64, macOS 14+ x64/arm64, dan Ubuntu 24.04
x64. Pengguna paket portable tidak memerlukan Python, Node.js, package manager,
atau database eksternal.

1. Ekstrak arsip release ke filesystem lokal yang writable.
2. Jalankan `LocalVault.exe`, `LocalVault.app`, atau executable `LocalVault` untuk
   platform terkait.
3. Launcher membuat `LocalVault-Data` di samping launcher, menjalankan server,
   menampilkan tray, dan membuka browser default.
4. Buka alamat loopback atau salin alamat IPv4 LAN dari menu tray. Port awalnya
   `8741`; server bind ke seluruh alamat IPv4 host (`0.0.0.0`). Firewall OS tetap
   dapat membatasi akses.
5. Gunakan menu tray untuk lock semua sesi atau menghentikan LocalVault. Jangan
   mematikan proses secara paksa ketika mutasi/restore sedang berlangsung.

Hanya satu proses boleh membuka satu `LocalVault-Data`. Direktori data harus
mendukung exclusive lock, `fsync`, dan atomic rename; network share yang tidak
dapat menjamin semantik tersebut tidak didukung.

### Data, backup, recovery, dan upgrade

`LocalVault-Data` berisi konfigurasi, SQLite encrypted envelope, backup, log, dan
instance lock. Jangan menghapus atau mengganti folder ini ketika memperbarui
aplikasi.

- Simpan recovery key di tempat terpisah. Tanpa master password atau recovery
  key yang valid, vault tidak dapat dipulihkan.
- Backup `.lvbak` tetap terenkripsi, tetapi retensi lokal bukan pengganti salinan
  backup eksternal.
- Backup historis dapat memerlukan master password/recovery key yang berlaku saat
  snapshot dibuat.
- Untuk upgrade, hentikan LocalVault dari tray, pertahankan `LocalVault-Data`,
  ganti hanya artefak aplikasi, lalu jalankan versi baru.

Panduan restore dan upgrade: [docs/RECOVERY_AND_UPGRADE.md](docs/RECOVERY_AND_UPGRADE.md).

## Development dari source

Baseline yang digunakan CI:

- Python 3.11;
- Node.js 24.x. Vite yang dipin memerlukan minimal Node `20.19.0` atau
  `22.12.0+` pada major yang lebih baru.

Dependency production, development, dan packaging dipisahkan di
`backend/requirements-*.txt`. `backend/requirements.lock` mengunci dependency
transitif beserta hash; `package-lock.json` adalah lockfile frontend.

### Setup Windows PowerShell

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
cd ..
npm ci
npm run build
cd backend
.\.venv\Scripts\python.exe run.py
```

### Setup macOS/Linux

```bash
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
npm ci
npm run build
cd backend
.venv/bin/python run.py
```

`run.py` menjalankan `QApplication`/tray pada main thread dan Uvicorn pada worker
thread. Dalam mode source, data dibuat di `backend/LocalVault-Data`. Direktori
tersebut diabaikan Git; jangan gunakan data nyata sebagai fixture pengujian.

Untuk hot reload frontend, biarkan launcher/backend berjalan, lalu dari root
repository jalankan:

```bash
npm run dev
```

Buka URL yang ditampilkan Vite (umumnya `http://127.0.0.1:5173`). Proxy development
meneruskan request `/api` ke `http://127.0.0.1:8741`.

## Build, test, dan audit

```bash
npm run build
npm test
npm run test:e2e
npm run audit
```

Backend (jalankan dari direktori `backend` dengan virtual environment aktif):

```bash
python -m pytest -q
```

Playwright memerlukan browser test yang sesuai. Instalasinya dapat dilakukan
dengan `npx playwright install` pada mesin development/CI. Test wajib memakai
direktori terisolasi dan tidak boleh menyentuh `backend/LocalVault-Data` pengguna.

Audit dependency Python yang digunakan dalam verifikasi:

```bash
uvx pip-audit -r backend/requirements.lock
```

Hasil pengujian yang telah dan belum ditutup dicatat di
[VERIFICATION.md](VERIFICATION.md). Kelulusan test lokal tidak dengan sendirinya
menyatakan seluruh acceptance test SRS §15 lulus.

## Membuat artefak release

PyInstaller tidak mendukung satu build lintas platform sebagai bukti
kompatibilitas. Jalankan build pada masing-masing OS target setelah dependency
dari lockfile terpasang.

Windows PowerShell:

```powershell
.\scripts\release.ps1
```

macOS/Linux:

```bash
./scripts/release.sh
```

Script membangun frontend lebih dahulu, membundel launcher/backend/aset dengan
PyInstaller, membuat arsip portable, SBOM Python CycloneDX, dan `SHA256SUMS`.
Artefak baru boleh dipublikasikan setelah release matrix, security audit, dan
seluruh gate SRS yang berlaku lulus terhadap byte artefak yang sama.

## Struktur repository

```text
localVault/
├── backend/
│   ├── localvault/          # FastAPI, domain, crypto, services, launcher
│   ├── tests/               # pytest + contract/regression/launcher tests
│   ├── LocalVault.spec      # konfigurasi PyInstaller
│   └── requirements*.txt    # dependency direct dan lock transitif
├── src/                     # React, TypeScript, i18n, dan unit tests
├── tests/e2e/               # Playwright workflows
├── scripts/                 # build release per platform
├── docs/                    # threat model serta recovery/upgrade
├── SRS.md                   # kontrak normatif LocalVault v1
└── VERIFICATION.md          # bukti dan gate release
```

## Dokumentasi

- [SRS.md](SRS.md) — kontrak normatif dan acceptance test v1;
- [VERIFICATION.md](VERIFICATION.md) — status bukti pengujian;
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) — batas perlindungan dan risiko;
- [docs/RECOVERY_AND_UPGRADE.md](docs/RECOVERY_AND_UPGRADE.md) — backup, restore,
  recovery, dan upgrade aman.

## Lisensi

LocalVault tersedia di bawah [MIT License](LICENSE).
